// ----资料----
## sync.Mutex

1. 正常模式
    1. **运行机制：**
        1. 当一个 Goroutine 尝试获取锁时，它会先进行自旋（Spinning）。
        2. 如果在自旋期间锁被释放了，该 Goroutine 会立刻抢占锁。
        3. 即使此时等待队列（FIFO 队列）中已经有其他 Goroutine 在排队，新来的 Goroutine 依然会和队列头部的 Goroutine **竞争**。
    2. **为什么新来的更容易抢到？**
    新来的 Goroutine 已经在 CPU 上运行，不需要经过上下文切换和唤醒过程。相比之下，从队列中唤醒的 Goroutine 需要重新调度，往往抢不过处于自旋状态的新 Goroutine。
2. 饥饿模式
    1. **触发条件：**
    当一个处于队列头部的 Goroutine 等待获取锁的时间超过了 **1 毫秒**，Mutex 就会从正常模式切换到饥饿模式。
    2. **运行机制：**
        1. **直接移交：** 锁的所有权会直接从解锁的 Goroutine 移交给队列头部的 Goroutine。
        2. **禁止抢占：** 在此模式下，新来的 Goroutine 不会尝试自旋，也不会尝试抢占，而是直接进入队列尾部排队。
    3. **退出条件：**
        1. 当前获锁的 Goroutine 是队列中的最后一个。
        2. 当前获锁的 Goroutine 等待时间小于 1 毫秒。

## sync.RWMutex

可以读读、不可以读写、写写，适合读多写少

## waitGroup

可以等待一组 Goroutine 的返回，用于批量发出 RPC 或者 HTTP 请求

## sync.Once

保证在 Go 程序运行期间的某段代码只会执行一次

## sync.Cond

可以让一组的 Goroutine 都在满足特定条件时被唤醒

一般情况下，我们都会先调用 `sync.Cond.Wait` 陷入休眠等待满足期望条件，当满足唤醒条件时，就可以选择使用 `sync.Cond.Signal` 或者 `sync.Cond.Broadcast` 唤醒一个或者全部的 Goroutine。

不常用，但是在条件长时间无法满足时，与使用 for {} 进行忙碌等待相比，sync.Cond 能够让出处理器的使用权，提高 CPU 的利用率。使用时我们也需要注意以下问题：

- sync.Cond.Wait 在调用之前一定要使用获取互斥锁，否则会触发程序崩溃；
- sync.Cond.Signal 唤醒的 Goroutine 都是队列最前面、等待最久的 Goroutine；
- sync.Cond.Broadcast 会按照一定顺序广播通知等待的全部 Goroutine；

## ErrGroup

封装了WaitGroup

```
type Group struct {
	cancel func()

	wg sync.WaitGroup

	errOnce sync.Once
	err     error
}
```

所以能够实现只接受第一个错误，然后用cancel取消其它任务

## Semaphore

支持加权申请、支持 Context 取消

## SingleFlight

在处理极高并发的请求时，针对同一个 Key，保证同一时刻只有一个协程在执行逻辑，其他协程阻塞等待结果，最后所有人共享同一个结果。

可用于防止缓存击穿


// ----问题----
1. sync.Mutex的正常模式
2. sync.Mutex的饥饿模式
3. sync.RWMutex的读写模式
4. sync.WaitGroup、sync.ErrGroup的用途
5. sync.Once的用途
6. sync.Cond的用途
7. sync.Semaphore的用途
8. sync.SingleFlight的用途

// ---go同步原语---
| 序号 | 上次考试日期 | 上次考试分数 | 下次考试日期 |
| --- | --- | --- | --- |
| 1 |
| 2 |
| 3 |
| 4 |
| 5 |
| 6 |
| 7 |
| 8 |