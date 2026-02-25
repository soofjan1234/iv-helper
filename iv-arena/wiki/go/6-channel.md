// ----资料----
# Go Channel

并发执行中，想要互相通信，一般都是共享内存，那么就可能引发竞态条件，得加锁，势必会造成性能影响。

而Go提倡通过通信来共享内存，而不是共享内存来实现通信

channel 是 goroutine 协程之间“安全地传值 + 同步”的工具

```markdown
ch := make(chan int) // 创建 channel（无缓冲）
ch <- 1              // 发送
x := <-ch            // 接收
close(ch)            // 关闭
```

## 源码

```go
type hchan struct {
	qcount   uint           // total data in the queue
	dataqsiz uint           // size of the circular queue
	buf      unsafe.Pointer // points to an array of dataqsiz elements
	elemsize uint16
	closed   uint32
	timer    *timer // timer feeding this chan
	elemtype *_type // element type
	sendx    uint   // send index
	recvx    uint   // receive index
	recvq    waitq  // list of recv waiters
	sendq    waitq  // list of send waiters
	bubble   *synctestBubble

	// lock protects all fields in hchan, as well as several
	// fields in sudogs blocked on this channel.
	//
	// Do not change another G's status while holding this lock
	// (in particular, do not ready a G), as this can deadlock
	// with stack shrinking.
	lock mutex
}

type waitq struct {
	first *sudog
	last  *sudog
}

```

1. 环形队列
    - **`buf`**: 指向实际存储数据的数组。
    - **`dataqsiz`**: 传送带的总长度（即 `make(chan int, 10)` 里的 10）。
    - **`qcount`**: 当前传送带上有多少个货（数据）。
    - **`sendx` / `recvx`**: 发送和接收的指针。因为是环形的，走到头会绕回 0。
2. 锁
    - 所有操作都要先加锁
3. 等待队列。当传送带满了（发不出去）或空了（拿不到货）时，Goroutine 不能死等，必须挂起。
    - **`recvq`**: 存放在这儿等着拿货的 Goroutine（买家）。
    - **`sendq`**: 存放在这儿等着送货的 Goroutine（卖家）。
    - **`sudog`**: 代表一个正在排队的 Goroutine 的封装。

### 发送

```go
func chansend(c *hchan, ep unsafe.Pointer, block bool, callerpc uintptr) bool {
	// 阻塞park 在 nil channel 上，按语言规范不会返回（所以后面 throw 不可达
	if c == nil {
		if !block {
			return false
		}
		gopark(nil, nil, waitReasonChanSendNilChan, traceBlockForever, 2)
		throw("unreachable")
	}

	...

	// 快速路径
	if !block && c.closed == 0 && full(c) {
		return false
	}

	...

	lock(&c.lock)

	// 写已关闭的会panic
	if c.closed != 0 {
		unlock(&c.lock)
		panic(plainError("send on closed channel"))
	}

	 // 有等待的接收者（直接交给接收者）
	if sg := c.recvq.dequeue(); sg != nil {
		send(c, sg, ep, func() { unlock(&c.lock) }, 3)
		return true
	}

	// 有缓冲且未满（写入 buf
	if c.qcount < c.dataqsiz {
		....
	}

	if !block {
		unlock(&c.lock)
		return false
	}

	// 无缓冲已满 或 有缓冲且 buf 满，且 block == true（阻塞
	// 当前 G 封装成 sudog mysg，挂在 sendq 上，然后 gopark，当前 G 阻塞
	gp := getg()
	mysg := acquireSudog()
	...
	c.sendq.enqueue(mysg)
	...
	gopark(chanparkcommit, unsafe.Pointer(&c.lock), reason, traceBlockChanSend, 2)

	KeepAlive(ep)

	// someone woke us up.
	...
	return true
}

// 把要发的值从 ep 拷到接收者的目标（sg.elem），不经过 buf，
// 然后 unlockf() 释放锁，goready(sg.g) 唤醒该 G
func send(c *hchan, sg *sudog, ep unsafe.Pointer, unlockf func(), skip int) {
	...
	if sg.elem != nil {
		sendDirect(c.elemtype, sg, ep)
		sg.elem = nil
	}
	gp := sg.g
	unlockf()
	gp.param = unsafe.Pointer(sg)
	sg.success = true
	if sg.releasetime != 0 {
		sg.releasetime = cputicks()
	}
	goready(gp, skip+1)
}

```

- **加锁**：`lock(&c.lock)`。
- **检查 `recvq`**：发现有没有人在门口等着拿货？
    - 如果有，直接把货塞给对方，**跳过 `buf`**（这叫直接拷贝，性能优化）。
- **检查 `buf`**：如果没人等，看看传送带满了吗？
    - 没满：把货放进 `buf[sendx]`，`sendx++`，`qcount++`。
- **阻塞**：如果满了，把当前 Goroutine 打包成 `sudog`，挂进 `sendq`，然后调用 `gopark` 睡觉。
- **解锁**。

### 接收

```go
// 在 channel c 上执行一次接收，把收到的数据写到 ep（若 ep == nil 则只“消费”不拷贝）
func chanrecv(c *hchan, ep unsafe.Pointer, block bool) (selected, received bool) {
	....
	if c == nil {
		if !block {
			return
		}
		gopark(nil, nil, waitReasonChanReceiveNilChan, traceBlockForever, 2)
		throw("unreachable")
	}

	...

// 快速路径
	if !block && empty(c) {
		...
	}

	...
	lock(&c.lock)

	if c.closed != 0 {
		if c.qcount == 0 {
			....
			return true, false
		}
		// 关闭但 buf 里还有数据，fall through 到后面从 buf 取
		// 不return 继续向下
	} else {
		// 未关闭且有等待的发送者
		if sg := c.sendq.dequeue(); sg != nil {
			recv(c, sg, ep, func() { unlock(&c.lock) }, 3)
			return true, true
		}
	}

 // 有缓冲且 buf 有数据
	if c.qcount > 0 {
		// Receive directly from queue
		...
	}

	if !block {
		unlock(&c.lock)
		return false, false
	}

	// 无数据且阻塞，进 recvq 并 park
	gp := getg()
	mysg := acquireSudog()
	...
	c.recvq.enqueue(mysg)
	...
	gopark(chanparkcommit, unsafe.Pointer(&c.lock), reason, traceBlockChanRecv, 2)

	// someone woke us up
	...
}

func recv(c *hchan, sg *sudog, ep unsafe.Pointer, unlockf func(), skip int) {
	if c.bubble != nil && getg().bubble != c.bubble {
		unlockf()
		fatal("receive on synctest channel from outside bubble")
	}
	if c.dataqsiz == 0 {
		...
		// 把 sender 的 sg.elem 拷到 ep
		if ep != nil {
			// copy data from sender
			recvDirect(c.elemtype, sg, ep)
		}
	} else {
		// 有缓冲（buf 满）
		// 从 buf 头部拿货，把发送者的货塞进 buf 尾部，唤醒对方
		qp := chanbuf(c, c.recvx)
		if raceenabled {
			racenotify(c, c.recvx, nil)
			racenotify(c, c.recvx, sg)
		}
		// copy data from queue to receiver
		if ep != nil {
			typedmemmove(c.elemtype, ep, qp)
		}
		// copy data from sender to queue
		typedmemmove(c.elemtype, qp, sg.elem)
		c.recvx++
		if c.recvx == c.dataqsiz {
			c.recvx = 0
		}
		c.sendx = c.recvx // c.sendx = (c.sendx+1) % c.dataqsiz
	}
	...
}

```

- **加锁**。
- **检查 `sendq`**：有没有人在门口等着发货？
    - 如果有，且 `buf` 为空：直接从发送者手里拿货，唤醒对方。
    - 如果有，且 `buf` 不为空：从 `buf` 头部拿货，把发送者的货塞进 `buf` 尾部，唤醒对方。
- **检查 `buf`**：如果没人等，看看 `buf` 里有货吗？
    - 有：取货，更新指针。
- **阻塞**：如果啥也没有，自己打包成 `sudog` 挂进 `recvq`，睡觉。
- **解锁**

### 快速路径

处理的是 select { case c <- x: ... default: ... } 这种场景。在「当前显然发不出去/收不到」时，希望**直接返回 false，不要抢锁**

```go
/*
发送的快速路径（chansend）:

	!block: 表示当前是非阻塞调用（即有 default 分支
	
	c.closed == 0: 观察到通道未关闭。

	full(c): 观察到通道已满（无缓冲且无接收者，或有缓冲且已满）
	
	如果这三个条件同时成立，函数直接返回 false，代表发送失败，执行 default
	*/
if !block && c.closed == 0 && full(c) {
		return false
	}
	
	func full(c *hchan) bool {
    if c.dataqsiz == 0 {
        return c.recvq.first == nil   // 无缓冲：没有人在等接收
    }
    return c.qcount == c.dataqsiz     // 有缓冲：buf 满了
}
```

```go
/*
接收的快速路径（chanrecv）:

	!block: 表示当前是非阻塞调用（即有 default 分支
	
	c.closed == 0: 观察到通道未关闭。

	empty(c): 观察到通道已空（无缓冲且无发送者，或有缓冲且空）
	
	*/
if !block && empty(c) {
    if atomic.Load(&c.closed) == 0 {
        return   // (false, false)
    }
    if empty(c) {
        if ep != nil {
            typedmemclr(c.elemtype, ep)
        }
        return true, false
    }
}
func empty(c *hchan) bool {
    if c.dataqsiz == 0 {
	    // 无缓冲：没有人在等发送
        return atomic.Loadp(unsafe.Pointer(&c.sendq.first)) == nil   
    }
    return atomic.Loaduint(&c.qcount) == 0   // 有缓冲：buf 里没数据
}
```

### 关闭

```go
func closechan(c *hchan) {
	if c == nil {
		panic(plainError("close of nil channel"))
	}
	...

	lock(&c.lock)
	if c.closed != 0 {
		unlock(&c.lock)
		panic(plainError("close of closed channel"))
	}
	
	// release all readers
	// release all writers (they will panic)
	...
}
```

1. 关闭未初始化的channel会panic
2. 关闭已关闭的也会panic

## 什么时候会被用到

1. 数据传递。两个协程之间传数据
2. 事件通知。等任务完成
3. 生产者 / 消费者。和第一点的不同在于：是持续的，不是一次；生产、消费速度可能不一样
4. 限制并发数。
    
    ```markdown
    sem := make(chan struct{}, 3)
    
    for i := 0; i < 10; i++ {
        sem <- struct{}{} // acquire
        go func(i int) {
            defer func() { <-sem }() // release
            fmt.Println(i)
            time.Sleep(time.Second)
        }(i)
    }
    ```
    
5. 多路复用与超时控制
    
    ```markdown
    ticker := time.NewTicker(time.Second)
    defer ticker.Stop()
    
    for {
        select {
        case <-ticker.C:
            fmt.Println("tick")
        case <-quit:
            return
        }
    }
    ```
    
6. 任务取消。本质是关闭一个广播 channel


// ----问题----
1. channel的使用场景有哪些
2. 对未初始化的的chan进行读写，会怎么样
3. 如何判断一个channel已经关闭
4. 往一个已经关闭的channel写、读数据会怎么样？
5. channel的发送流程
6. channel的接收流程
7. 关闭已关闭的channel、关闭未初始化的channel会怎么样

// ---channel---
| 序号 | 上次考试日期 | 上次考试分数 | 下次考试日期 |
| --- | --- | --- | --- |
| 1 | 2026-02-24 | 4.25 | 2026-02-27 |
| 2 |
| 3 |
| 4 |
| 5 |
| 6 |
| 7 |