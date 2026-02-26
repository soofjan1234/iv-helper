// ----资料----
## sync.Mutex

- **Normal（正常）**：
    - 等待者按 FIFO 排队，但被唤醒的 waiter 要和**新来的** goroutine 一起抢锁；新来的已经在跑，容易抢到，waiter 可能一直抢不到。
    - 若某个 waiter 抢了超过 **1ms** 还没拿到，就切到 **starvation**。
- **Starvation（饥饿）**：
    - 不再把锁交给「新来的」，而是**直接交给队头 waiter**；新来的也不自旋，直接排队。
    - 这样能避免某个 waiter 长期拿不到锁（避免尾延迟极差）。
    - 当「被交接到锁的 waiter 发现自己是最后一个」或「自己等待时间 < 1ms」时，再切回 normal。

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
| 1 | 2026-02-26 | 4.25 | 2026-02-29 |
| 2 |
| 3 |
| 4 | 2026-02-26 | 4.0 | 2026-02-28 |
| 5 |
| 6 |
| 7 |
| 8 |