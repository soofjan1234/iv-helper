// ----资料----
# 一、Go Channel

```markdown
ch := make(chan int) // 创建 channel（无缓冲）
ch <- 1              // 发送
x := <-ch            // 接收
close(ch)            // 关闭
```

channel 是 goroutine 协程之间“安全地传值 + 同步”的工具

## 1. 什么时候会被用到

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

## 2.问题

### 1. 对未初始化的的chan进行读写，会怎么样

读写未初始化的chan都会阻塞。

### 2. 如何判断一个channel已经关闭

1. **`value, ok := <-ch`：**通过 `ok` 判断 channel 是否关闭
2. **`for range` 遍历 `channel：`**当 channel 关闭时循环结束

### 3. 往一个已经关闭的channel写、读数据会怎么样？

1. **写数据：**立即 panic
2. **读数据：**有数据正常读取；无数据返回零值
3. **关闭已关闭的也会panic**

// ----问题----
1. channel的使用场景有哪些
2. 对未初始化的的chan进行读写，会怎么样
3. 如何判断一个channel已经关闭
4. 往一个已经关闭的channel写、读数据会怎么样？
