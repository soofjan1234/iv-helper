// ----资料----
# GMP是怎么来的

## 传统多线程

在操作系统中，一个CPU核运行多个线程来提高并发处理的能力，然而多个线程的创建、切换使用、销毁开销通常较大：

1. 内存成本：一个线程通常是1~8M
2. 时间成本：切换的时候需要存当前线程的上下文（寄存器、程序计数器、栈指针）到内存里，再取下一个线程的上下文
3. 权限成本：创建、销毁、调度必须通过系统调用，向操作系统内核申请资源

## 单线程调度器

为解决这个问题，Go 引入了**用户态调度**的思想，将线程分成了两种：内核级线程 Machine，轻量级的用户态的协程 Goroutine。

M负责申请资源，执行G，G是任务指令。一个M可以绑定多个G，这些G都放在全局队列里。

那么切换G执行的时候，就像在同一个房间里换人说话，无需进入内核态，内存开销极小。

为了防止在添加或提取 G 时发生混乱，Go 引入了一把**全局锁 (`schedlock`)**。只有拿到锁，M 才能去全局队列里挑选下一个要执行的 G。

## 多线程调度器

接着为了实现真正的并行，利用多核 CPU。Go从单线程改为多线程调度器，多个M对应多个G，但

1. M 变多，这把全局锁就成了系统的**交通瓶颈。**
2. 而且当一个 G 产生另一个 G 时，老调度器往往把它丢回全局队列，或者需要 M 之间互相喊话传递。这一来一回，也消耗了时间
3. 当G在M1跑的时候，M1的CPU缓存有它的数据，但是G阻塞回来，可能是M2接手它，而缓存是空的，它就得从内存搬东西过来。
4. 一个G发起阻塞的系统调用的时候，M也挂起了，那么它绑定的其它G也跟着一起睡了

## 任务窃取调度器-GMP 模型

为了解决多线程调度器的问题，在 GM 基础上，引入了 P 处理器，并在 P 的基础上实现基于工作窃取的调度器。

1. 引入 P 后，每个 M 不再直接去全局队列抢活，而是先绑定一个 P。
    1. 每个 P 维护着一个**私有的本地任务队列**
    2. M 只需要在自己的 P 里拿 G
    3. 只有本地队列空了，才去全局队列拿
2. 当一个正在运行的 G 产生了一个新 G，优先放入当前 P 的本地队列
3. Go 把内存缓存（mcache）从 M 身上剥离，转而**绑定在 P 身上**。
    1. G只跟着P走，假设M换了，P身上还是有热缓存
4. 当 M 因为 G 的系统调用被内核挂起时，会立刻抛弃P
    1. 调度器会叫一个空闲的M来接管这个P

故P (Processor)，在 G 与 M 之间充当了“资源管家”的角色

**Work Stealing (任务窃取)**

当一个 P 空闲，另一个 P 很忙，M 会从该 P 的 本地队列尾部窃取 一半（至少 1 个）G

## 抢占式调度器

虽然有了 GMP 和工作窃取，但如果某个 G 是个“死循环”或者执行时间极长，它不主动让出 M，别的 G 还是没机会跑。为了公平，Go 引入了**抢占机制**，经历了两个阶段的进化：

**基于协作的抢占（Go 1.14 之前）**

为什么叫“协作”？因为调度器不能直接停掉 G，它必须等 G **自己停下来**。

1. 编译器会在函数的开头（或结尾）偷偷插入几行汇编代码，叫 `stack check`
2. 调度器发现 G1 跑了太久（比如 10ms），就给这个 G1 打个标记：`stackguard0 = stackPreempt`
3. G1 继续跑，当它运行到下一个函数调用时，会执行那段秘密的 `stack check` 代码
4. G1 一看，内存检测发现我不该继续跑了，于是它会主动调用 `runtime.goschedImpl`，自己把自己搬下台，把 M 让出来

**为什么它会失效？**如果 G 里写的是 `for { i++ }`，里面就没有任何函数调用

**基于信号的抢占（Go 1.14 至今）**

通过**操作系统**强制介入

1. Go给 **M** 注册了一个 sighandler
2. **监控者（sysmon）**发现 M 上的 G 运行超过 10ms 了，且这哥们一直没下台，向 **M** 发送一个信号：SIGURG。
3. 只要信号一到，**操作系统内核**会立刻暂停 M1 的当前工作。
4.  M1 会被迫跳转去执行 sighandler。在这个函数里，会直接操作 M1 的寄存器（PC 等），在当前的执行位置强行塞进一个叫 asyncPreempt 的函数调用。
5. 当内核恢复 M1 的执行时，M1 以为自己还在接着刚才的代码跑，结果跑的第一行代码就是被塞进去的 asyncPreempt
6. asyncPreempt 会通过mcall切换到 g0 栈（这是 Go 调度器的专属后台通道）。在 g0 栈里，它运行 `gopreempt_m`，正式把 G1 踢回全局队列。M1 拍拍灰，去帮其他 P 找活干了。

## 为什么 goroutine比较轻量

1. **快速创建/销毁**
2. **内存占用极低：**初始栈大小仅 2KB（对比线程通常 1-8MB 并且是静态分配），动态增长收缩
3. **用户态调度（零内核开销）**：线程的创建和切换都需要进入内核
4. **GMP调度效率优化**
5. **数量优势：**操作系统通常可以处理的线程数量在数百到几千个之间；Go 运行时可以轻松地创建和管理成千上万的协程

# GMP结构

### **G (Goroutine)**

每个协程，包含了一个**执行上下文（如栈、指令指针等）和一个调度状态**

```go
type g struct {
	// ----**执行上下文----**
	stack       stack   // 栈内存范围 [lo, hi)
	stackguard0 uintptr // 栈增长检查/抢占
	sched       gobuf   // 被切走时保存的现场，恢复时从这里继续执行
	
	// ----**调度状态----**
	m            *m      // 当前正在执行本 G 的 M（OS 线程）
	atomicstatus uint32  // G 的状态：可运行/运行中/等待/系统调用等
	goid         uint64  // goroutine ID
	schedlink    guintptr // 在调度链表中的下一个 G
	waitsince    int64    // 进入等待状态的大致时间
	waitreason   waitReason // 等待原因（等 channel、锁、timer 等）
	...
}

type gobuf struct {
	sp   uintptr // 栈指针，恢复时写回 CPU
	pc   uintptr // 指令指针（下一条要执行的地址）
	g    guintptr // 当前 gobuf 所属的 G（用于栈扫描等）
	ctxt unsafe.Pointer // 闭包/上下文，恢复时写回
	...
}
```

### **M (Machine)**

一个操作系统线程

```go
type m struct {
	g0   *g  // 持有调度栈的 Goroutine
	curg *g  // 在当前线程上运行的用户 Goroutine
	...
}

```

g0深度参与运行时的调度过程，包括 Goroutine 的创建、大内存分配和 CGO 函数的执行

### **P (Processor)**

负责管理运行时的调度队列，决定哪些 G 应该被执行

```go
type p struct {
	m           muintptr

	// 处理器持有的运行队列
	runqhead uint32
	runqtail uint32
	runq     [256]guintptr
	runnext guintptr
	
	// 二手循环中心，存放执行完的Goroutine
	gFree gList
	
	...
}

```

## **Schedt (Scheduler Type)**

调度器的schedt结构体存储了全局的 G 队列，空闲的 M 列表和 P 列表：

```go
type schedt struct {
	 lock mutex            // schedt的锁
	 
	 midle        muintptr // 空闲的M列表
	 nmidle       int32    // 空闲的M列表的数量
	 nmidlelocked int32    // 被锁定正在工作的M数
	 mnext        int64    // 下一个被创建的 M 的 ID
	 maxmcount    int32    // 能拥有的最大数量的 M
	 
	 pidle      puintptr   // 空闲的 P 链表
	 npidle     uint32     // 空闲 P 数量
	 nmspinning uint32     // 处于自旋状态的 M 的数量
	 
	 // 全局可执行的 G 列表
	 runq     gQueue
	 runqsize int32        // 全局可执行 G 列表的大小
	 
	 // 全局 _Gdead 状态的空闲 G 列表
	 gFree struct {
	  lock    mutex
	  stack   gList // Gs with stacks
	  noStack gList // Gs without stacks
	 }
	 
	 // sudog结构的集中存储
	 sudoglock  mutex
	 sudogcache *sudog
	 // 有效的 defer 结构池
	 deferlock mutex
	 deferpool *_defer
   ...
}
```

## GMP的关系
角色定义：
1. G (Goroutine)：协程，即待执行的任务和其上下文。
2. M (Machine)：物理线程，由操作系统内核管理，是真正的执行单元。
3. P (Processor)：逻辑处理器，代表运行协程所需的资源和上下文。

运行逻辑：
1. 绑定机制：M 必须与一个 P 绑定（M-P 组合）后，才能执行 G。
2. 队列结构：每个 P 维护一个本地本地队列（Local Queue）；此外还有一个存放待运行 G 的全局队列（Global Queue）。

# 调度器流程

## 启动

当Go程序运行时，真正启动函数是 runtime·rt0_go，主要功能

1. 初始化 m0 和 g0：m0 ****是 Go 程序启动后的第一个主线程，g0是专门用来执行“调度代码”的特殊协程
2. schedinit：把调度器、内存、模块、GC、P 等环境准备好
3. newproc：创建了第一个真正的 Goroutine
4. mstart：开始启动调度器的调度循环

schedinit 中，会创建 GOMAXPROCS 个处理器 p ，这些处理器会绑定到不同的内核线程上，所以最多会有 GOMAXPROCS线程活跃

```go
// src/runtime/proc.go
// 调度器初始化
func schedinit() {
 ...
 // 设置机器线程数M最大为10000
 sched.maxmcount = 10000
 ...
 // 栈、内存分配器相关初始化
 stackinit()          // 初始化栈
 mallocinit()         // 初始化内存分配器
 ...
 // 初始化当前系统线程 M0
 mcommoninit(_g_.m, -1)
 ...
 // GC初始化
 gcinit()
 ...
 // 设置P的值为GOMAXPROCS个数
 procs := ncpu
 if n, ok := atoi32(gogetenv("GOMAXPROCS")); ok && n > 0 {
  procs = n
 }
 // 调用procresize调整 P 列表
 if procresize(procs) != nil {
  throw("unknown runnable goroutine during bootstrap")
 }
 ...
}

```

## 创建G

```go
func newproc(fn *funcval) {
	gp := getg()
	pc := sys.GetCallerPC()
	systemstack(func() {
		newg := newproc1(fn, gp, pc, false, waitReasonZero)

		pp := getg().m.p.ptr()
		runqput(pp, newg, true)

		if mainStarted {
			wakep()
		}
	})
}
```

**初始化结构体（newproc1）**

```go
// 获取或创建g 然后设为 Grunnable（或 _Gwaiting）
func newproc1(...) *g {
	...
	newg := gfget(pp)
	...
	var status uint32 = _Grunnable
	if parked {
		status = _Gwaiting
	}
	...
}
```

在gfget函数中，从 P 的本地 gFree 里 pop 一个 G；若本地空了，先从全局 sched.gFree 搬一批到本地，再 pop。

拿到后根据栈情况：要么沿用旧栈，要么释放旧栈再分配新栈，最后返回一个可用的 *g。

```go
func gfget(pp *p) *g {
retry:
	// ① 本地 gFree 空了且全局还有 → 加锁，从全局最多搬 32 个到本地，再重试
	if pp.gFree.empty() && (!sched.gFree.stack.empty() || !sched.gFree.noStack.empty()) {
		lock(&sched.gFree.lock)
		for pp.gFree.size < 32 {
			...
		}
		unlock(&sched.gFree.lock)
		goto retry
	}

	// ② 从本地 pop 一个；没有就返回 nil（调用方会 new 新 G）
	gp := pp.gFree.pop()
	if gp == nil {
		return nil
	}

	// ③ 有栈但尺寸已不是默认 → 释放旧栈，标记为无栈
	if gp.stack.lo != 0 && gp.stack.hi-gp.stack.lo != uintptr(startingStackSize) {
		...
	}

	// ④ 无栈 → 分配一块新启动栈并设 stackguard0
	if gp.stack.lo == 0 {
		...
	} else {
		// ⑤ 有栈 → 只做 race/msan/asan 相关处理
		// 辅助发现内存/并发问题
		...
	}
	return gp
}
```

**运行队列（runqput）**

```go
const randomizeScheduler = raceenabled

func runqput(pp *p, gp *g, next bool) {
	// ① 无 sysmon 时不用 runnext，避免一对 G 占满时间片导致饥饿
	if !haveSysmon && next {
		next = false
	}
	// race 时 50% 放弃 runnext，随机化调度
	if randomizeScheduler && next && randn(2) == 0 {
		next = false
	}

	// ② next=true：CAS 把 gp 放进 pp.runnext；若挤掉原来的 runnext，把被挤掉的 G 当作 gp 放进下面队尾
	if next {
	retryNext:
		oldnext := pp.runnext
		if !pp.runnext.cas(oldnext, guintptr(unsafe.Pointer(gp))) {
			goto retryNext
		}
		if oldnext == 0 {
			return  // 原来没 runnext，只放了 gp，结束
		}
		gp = oldnext.ptr()  // 被挤出来的 G 要放进本地队尾
	}

retry:
	// ③ 本地 runq 未满：放到 runq[tail]，tail++
	h := atomic.LoadAcq(&pp.runqhead)
	t := pp.runqtail
	if t-h < uint32(len(pp.runq)) {
		pp.runq[t%uint32(len(pp.runq))].set(gp)
		atomic.StoreRel(&pp.runqtail, t+1)
		return
	}
	// ④ 本地满了：把一半本地 + gp 搬到全局队列，成功就返回
	if runqputslow(pp, gp, h, t) {
		return
	}
	goto retry  // 没搬成（队列被消费了），再试一次
}
```

next为true，则放到下一个运行；否则放队尾

1. 对next=true进行了两次拦截：
    1. 没有监工（sysmon）时，不允许插队。因为两个 G 如果互相不停地创建对方并插队，就会永远霸占 CPU，导致其他 G 饿死
    2. 竟态检测（randomizeScheduler）时，50%几率踢出VIP
2. 如果 next 为true，进入runnext
    1. 通过 cas （原子操作）把新G 放进 pp.runnext，结束
    2. 如果 runnext 有老G，设现有 gp 为老G
3. 不管是新G，还是老G，都是gp，走到现在，都得放队尾了
    1. 如果满了，通过 runqputslow 把一半本地 + gp 搬到全局队列，成功就返回

关于randomizeScheduler = raceenabled

有些测试或代码其实**隐式依赖**“G 一定按某种顺序被调度”（例如以为 A 一定在 B 前面跑、或一定先被调度到）。顺序一变就挂，但平时看不出来。

开 -race 时给调度加随机，是为了揪出那些“以为 G 会按某种顺序跑”的隐藏依赖；通过 -race 的测试就不该再依赖调度顺序。

## 调度循环

```go
func schedule() {
	...
	gp, inheritTime, tryWakeP := findRunnable()
	...
	execute(gp, inheritTime)
}
```

```go
	func findRunnable() (gp *g, inheritTime, tryWakeP bool) {
		...
		// 特殊 G（trace、GC worker）、周期性看全局（公平性）
		// trace reader
		if traceEnabled() || traceShuttingDown() {
			...
		}
		// GC worker
		if gcBlackenEnabled != 0 {
			...
		}
		// 每 61 个 tick 看一次全局队列，保证公平
		if pp.schedtick%61 == 0 && !sched.runq.empty() {
			...
		}
		
		// 本地 runq（runqget 内部先看 runnext，再看 runq）
		if gp, inheritTime := runqget(pp); gp != nil {
			...
		}
		
		// 全局 runq
		if !sched.runq.empty() {
		 ...
		}
		
		// 网络 poll（netpoller）
		if netpollinited() && netpollAnyWaiters() && ... {
			...
		}
		
		// 偷取（stealWork → runqsteal）
		if mp.spinning || 2*sched.nmspinning.Load() < gomaxprocs-sched.npidle.Load() {
			if !mp.spinning {
				mp.becomeSpinning()
			}
			...
		}
		
		// 仍没有：让出 P、阻塞等活
		...
	}
```

## 触发调度

**正常调度**

g 顺利执行完成，并进入下一次调度循环

**主动调度**

```jsx
func Gosched() {
	checkTimeouts()
	mcall(gosched_m)
}
func gosched_m(gp *g) {
	goschedImpl(gp, false)
}
func goschedImpl(gp *g, preempted bool) {
	...
	casgstatus(gp, _Grunning, _Grunnable)
	if trace.ok() {
		traceRelease(trace)
	}

	dropg()
	lock(&sched.lock)
	globrunqput(gp)
	unlock(&sched.lock)

	...

	schedule()
}
```

当业务代码主动调用 runtime.Gosched() 函数时

1. 将 G 从 running 状态变为 runnable
2. dropg() 释放 M 当前运行的 G
3. globrunqput 将 G 放入全局运行队列 sched.runq
4. 开始 schedule() 调度

**被动调度**

```jsx
// 被阻塞
func gopark(...) {
	...
	mcall(park_m)
}
func park_m(gp *g) {
	...
	casgstatus(gp, _Grunning, _Gwaiting)
	if trace.ok() {
		traceRelease(trace)
	}

	dropg()
	...
	schedule()
}

// 被唤醒
func goready(gp *g, traceskip int) {
	systemstack(func() {
		ready(gp, traceskip, true)
	})
}
func ready(gp *g, traceskip int, next bool) {
	...
	casgstatus(gp, _Gwaiting, _Grunnable)
	..
	runqput(mp.p.ptr(), gp, next)
	wakep()
	releasem(mp)
}
```

G 在代码里碰到了 Channel 阻塞、Mutex 锁、`time.Sleep` 或者网络请求：

1. 通过 runtime.mcall 切换到 g0 的栈上调用 runtime.park_m
2. 将 G 从 running 状态变为 waiting
3. G 被放到**对应资源的等待链表**，比如被放到 Channel 对象里

当要被唤醒时：

1. 将 G 从 waiting 状态变为 runnable
2. 放入本地运行队列等待被调度
3. wakep()：检查一下有没有闲着的 P，有就唤醒 M 来干活，充分利用性能

**抢占调度**

轮到sysmon出场了

```jsx
.func sysmon() {
	...
	// 初始休眠 20μs，如果不干活的时间长了，最长会休眠 10ms
	for {
	    if idle == 0 { delay = 20 } 
	    else if idle > 50 { delay *= 2 }
	    if delay > 10000 { delay = 10000 }
	    usleep(delay)
	    ...
	    // poll network if not polled for more than 10m
	    lastpoll := sched.lastpoll.Load()
	    if (...) {
		    injectglist(&list) // 发现有就绪的 G，扔进全局队列
	    }
	    // 抢占(Preemption)与接管(Retake)
	    if retake(now) != 0 {
				idle = 0
			} else {
				idle++
			}
			// check if we need to force a GC
			if ... {
				injectglist(&list) // 把专门负责强行 GC 的辅助 goroutine 扔进队列运行
			}
	}
}
```

sysmon 的职责：

1. **抢占长时间运行的 G (Preemption)**：监控是否有 Goroutine 运行超过了 10ms。如果有，就给它打个标记，强迫它让出 CPU。
2. **接管陷入系统调用的 P (Retake)**：如果一个 Goroutine 进入了系统调用（Syscall）太久，占着 P 不拉屎，**sysmon** 会剥离这个 P，让 P 去运行其他的 G。
3. **网络轮询 (Netpoll)**：如果调度器因为太忙好久没检查网络事件了，**sysmon** 会顺便检查一下是否有就绪的网络 IO，并唤醒对应的 G。
4. **强制 GC (Force GC)**：如果系统已经 2 分钟没有发生过 GC 了，**sysmon** 会强行启动一次垃圾回收过程

```jsx
func retake(now int64) uint32 {
	...
	for i := 0; i < len(allp); i++ {
		...
		s := pp.status
		if s == _Prunning || s == _Psyscall {
		    // 如果调度记数 (schedtick) 没变，说明同一个 G 跑了很久
		    if t.schedtick != pp.schedtick {
	        ...
		    } else if t.schedwhen + forcePreemptNS <= now {
	        preemptone(pp) // 重点：向该 G 发起信号或标记，强制它停下来
		    }
		}
		// 约 L6272
		if s == _Psyscall {
		    // 如果系统调用记数没变，且经过了一次 sysmon tick (10ms左右)
		    if t.syscalltick != pp.syscalltick {
		        ...
		        continue
		    }
		    // 如果超过时间或没有空闲 P 且有排队的 G，就强行收回 P
		    if runqempty(pp) && 
			    sched.nmspinning.Load() + sched.npidle.Load() > 0 && 
		       t.syscallwhen + 10*1000*1000 > now {
		        continue
		    }
		    if handoffp(pp) { n++ } // 重点：把 P 抢走，交给别人去干活
		}
	}
}
```

```jsx
func preemptone(pp *p) bool {
	...
	// 协作式抢占
	gp.preempt = true
	gp.stackguard0 = stackPreempt
	
	// 信号抢占
	if preemptMSupported && debug.asyncpreemptoff == 0 {
		pp.preempt = true
		preemptM(mp)
	}
}

func preemptM(mp *m) {
	...
	signalM(mp, sigPreempt)
	...
}
```

```jsx
func handoffp(pp *p) {
	// 本地队列或者全局队列有活，直接找 M 来接管 P
	if !runqempty(pp) || sched.runqsize != 0 {
		startm(pp, false, false)
		return
	}
	// 如果有 Trace（追踪）任，或者有 GC（垃圾回收）的任务
	if (traceEnabled() || traceShuttingDown()) && traceReaderAvailable() != nil {
		startm(pp, false, false)
		return
	}
	if gcBlackenEnabled != 0 && gcMarkWorkAvailable(pp) {
		startm(pp, false, false)
		return
	}
	// 如果发现系统里既没有空闲的处理器
	// 也没有正在找活干的“自旋线程
	// 说明系统可能陷入静默。这时候必须强行启动一个 M
	if sched.nmspinning.Load()+sched.npidle.Load() == 0 && sched.nmspinning.CompareAndSwap(0, 1) { // TODO: fast atomic
		sched.needspinning.Store(0)
		startm(pp, true, false)
		return
	}
	...
	// 放进全局的空闲 P 链表里
	// 直到下次有新的 G 被创建时被 wakep 唤醒。
	when := pp.timers.wakeTime()
	pidleput(pp, 0)

	if when != 0 {
		wakeNetPoller(when)
	}
}
```

 

**系统调用**

Go 中使用Syscall 函数进行系统调用

```jsx
func Syscall(trap, a1, a2, a3 uintptr) (r1, r2 uintptr, err syscall.Errno) {
	syscall.Entersyscall() // 进入系统调用前的准备工作
	r, errno := realSyscall(trap, a1, a2, a3, 0, 0, 0, 0, 0, 0)
	syscall.Exitsyscall() // 系统调用结束后的收尾工作
	return r, 0, syscall.Errno(errno)
}
```

```jsx
func entersyscall() {
	fp := getcallerfp()
	reentersyscall(sys.GetCallerPC(), sys.GetCallerSP(), fp)
}
func reentersyscall(pc, sp, bp uintptr) {
	... 
	pp := gp.m.p.ptr() // 获取当前 G 所在的 P
	pp.m = 0 // 解除当前 P 和 M 之间的关联
	gp.m.oldp.set(pp) // 把 P 记录在 oldp 中，等从系统调用返回时，优先绑定这个 P
	gp.m.p = 0 // 解除当前 M 和 P 之间的关联
  // 修改当前 P 的状态，sysmon 线程依赖状态实施抢占
	atomic.Store(&pp.status, _Psyscall)
	...
}
```

当一个 Goroutine (G) 完成系统调用想回来工作时，它必须先抢到一个 P（处理器）。

1. **快速路径 (exitsyscallfast)**：它尝试找回之前用的那个 P，或者随便抢一个空闲的 P。
2. **慢速路径 (exitsyscall0)**：如果运气很差，**全公司的 P 都在忙**，一个空位置都没有。这时候，当前线程 (M) 就没法继续跑这个 G 了。

```jsx
func exitsyscall() {
	gp := getg()
	...
	oldp := gp.m.oldp.ptr()
	gp.m.oldp = 0
	// 尝试获取p
	if exitsyscallfast(oldp) {
		...
		return
	}

	// Call the scheduler.
	mcall(exitsyscall0)
	...
}

func exitsyscallfast(oldp *p) bool {
	...
	// Try to re-acquire the last P.
	trace := traceAcquire()
	if oldp != nil && oldp.status == _Psyscall && atomic.Cas(&oldp.status, _Psyscall, _Pidle) {
		// There's a cpu for us, so we can run.
		wirep(oldp)
		...
		return true
	}
	...
	// Try to get any other idle P.
	if sched.pidle != 0 {
		var ok bool
		systemstack(func() {
			ok = exitsyscallfast_pidle()
		})
		if .ok {
			return true
		}
	}
	return false
}

func exitsyscall0(gp *g) {
	...
	// 将 G 的状态从 _Gsyscall 切换为 _Grunnable
	casgstatus(gp, _Gsyscall, _Grunnable)
	...
	// 释放当前 G，解除和 M 的关系
	dropg()
	lock(&sched.lock)
	var pp *p
	// 尝试从空闲 P 队列中获取 P
	if schedEnabled(gp) {
		pp, _ = pidleget(0)
	}
	var locked bool
	if pp == nil {
		// 如果未获取到 P，将 G 放入全局运行队列
		globrunqput(gp)

		...
	} 
	...
	unlock(&sched.lock)
	if pp != nil {
		// 绑定 M 和 P， 执行调度
		acquirep(pp)
		execute(gp, false) // Never returns.
	}
	...
	stopm()    // 当前线程 M 停止执行，进入休眠状态
	schedule() // 永不返回：直到 M 被唤醒并分配了新的 P 和 G
}
```

// ----问题----
1. 讲讲多线程模型的问题，以及单线程调度器
2. 讲讲多线程调度器以及他的问题
3. 讲讲任务窃取调度器
4. 讲讲基于协作、基于信号的抢占式调度器
5. go协程为什么轻量
6. 讲讲G、M、P的关系
7. goroutine有哪些阻塞场景，怎么处理?

// ---go并发---
| 序号 | 上次考试日期 | 上次考试分数 | 下次考试日期 |
| --- | --- | --- | --- |
| 1 | 2026-02-26 | 3.5 | 2026-02-28 |
| 2 |
| 3 |
| 4 |
| 5 | 2026-02-24 | 4.5 | 2026-02-27 |
| 6 | 2026-03-04 | 4.0 | 2026-03-08 |
| 7 |

