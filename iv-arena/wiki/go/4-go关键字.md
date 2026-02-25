// ----资料----
# Select

## Select是什么

select 是与 switch 相似的控制结构，与 switch 不同的是，select 中虽然也有多个 case，但是这些 case 中的表达式必须都是 Channel 的收发操作

## Select出现的现象

1. 空的select语句会阻塞，导致 Goroutine 进入无法被唤醒的永久休眠状态。
2. 单一case，会改为if语句
    
    ```go
    // 改写前
    select {
    case v, ok <-ch: // case ch <- v
        ...
    }
    
    // 改写后
    if ch == nil {
        block()
    }
    v, ok := <-ch // case ch <- v
    ...
    ```
    
3. select 能在 Channel 上进行非阻塞的收发操作，使用default关键字；
4. select 在遇到多个 Channel 同时响应时，会随机执行一种情况

# Defer

## Defer是什么

在Go里可以放在某个函数或者方法调用的前面，让该函数或方法返回前执行。

如果是函数是因为调用了`os.Exit()`而退出，那`defer`就不会被执行了

同时它是后进先出，倒序执行

# Panic和Recover

panic就是你可以自己调用或者是说运行时有错误，比如数组越界。

然后流程大概是这样的。如果呢你在F函数里面遇到了panic，那么它就会停止运行下面的东西，而是只运行defer函数的东西，然后呢回到上一层。

**对于标准Go编译器，有些致命错误是无法被recover捕捉的，比如栈溢出(stack overflow)或者内存超限(out of memory)，遇到这种情况程序就会crash**

pnic本身不会打印东西，他呢会把defer都执行完，然后完成这个栈展开，最后呢由runtime统一打印并终止程序。

panic跨协程失效

recover就是和panic配套使用的对吧？panic就是发生错误，recover呢就是恢复。然后recover必须是在defer里面执行才是有效的。

一般recovery为nil的有三种情况。第一种情况呢就是panic传过去的值，它就是nil。第二种情况就是没有panic。第三种情况呢就是它没有写到defer下面去。

# Make和New

make呢是为了初始化它们的切片，数组，还有通道，为里面的值呢分配内存空间。

new是初始化一个参数，并为它分配空间，是参数对应的零值，参数只有一个，什么类型都可以，接着返回一个指针。

为什么针对slice, map和chan类型专门定义一个make函数？

因为如果是只有nil或者什么都没有的话，他们初始的时候呢，就是一个nil值，当为nil值的时候map添加map元素会panic，然后通道的话会阻塞s是可以append，但是我们可能也希望给它初始化一个长度什么的。

为什么slice是nil也可以直接append？

因为如果为nil值的话，他会给他分配一个内存空间。

// ----问题----
1. select 的常见现象有哪些（如随机性、阻塞行为）？
2. defer 的执行顺序是怎样的？在什么情况下 defer 不会被执行？
3. 简述 panic 和 recover 的执行流程。哪些错误是 recover 无法捕获的？
4. recover为nil的情况有哪些？
5. make 和 new 的区别是什么？各自的适用场景有哪些？
6. 为什么 slice、map 和 chan 类型需要专门提供 make 函数而不能仅靠 new？
7. slice 为 nil 时为什么可以直接 append 而不报错？

// ---go关键字---
| 序号 | 上次考试日期 | 上次考试分数 | 下次考试日期 |
| --- | --- | --- | --- |
| 1 |
| 2 | 2026-02-24 | 4.0 | 2026-02-26 |
| 3 |
| 4 |
| 5 | 2026-02-24 | 3.75 | 2026-02-26 |
| 6 |
| 7 |
