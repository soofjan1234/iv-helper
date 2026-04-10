// ----资料----

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
| 2 | 2026-03-04 | 4.0 | 2026-03-08 |
| 3 | 2026-03-06 | 3.5 | 2026-03-09 |
| 4 |
| 5 | 2026-02-24 | 4.5 | 2026-02-27 |
| 6 | 2026-03-04 | 4.0 | 2026-03-08 |
| 7 |

