// ----资料----
---
title: context
description: 理解 context 的语义与相互关系
---

# context 

`context` 的核心作用：在 **API 边界** 与 **进程内多个 goroutine** 之间传递同一套“请求范围”信息。

它主要包含三类信息：
- **截止时间 deadline**
- **取消信号 cancellation**（以及取消原因）
- **请求范围 values**（通过 `Value(key)` 取出）

---

## 1) Context 接口：你能“读到”的四件事

| 方法 | 语义 |
|---|---|
| `Deadline() (t, ok)` | 是否设置截止时间；到点应该取消 |
| `Done() <-chan struct{}` | 只读取消通道：取消时会被 close |
| `Err() error` | 被取消后的原因（如 `context.Canceled` / `context.DeadlineExceeded`） |
| `Value(key any) any` | 从当前 context 及其父链向上查找对应 value；找不到返回 `nil` |

---

## 2) 根节点：Background / TODO

- `context.Background()`：明确这是根（`main`、初始化、测试起点）
- `context.TODO()`：临时占位（还不确定该传什么）

它们都是“不可取消/没有值”的起点，因此不会产生向下取消效果。

---

## 3) 常用构造器对照表（你该怎么用）

| 构造器 | 生成的语义变化 | 取消/截止行为 | Value 行为 |
|---|---|---|---|
| `WithCancel(parent)` | 变成“可取消的子节点” | `cancel()` 会关闭 `Done()`，并设置 `Err()` | Value 不改：沿父链查 |
| `WithDeadline(parent, d)` | 引入截止时间 | 到点触发取消，`Err()` 可能是 `DeadlineExceeded` | Value 沿父链查 |
| `WithTimeout(parent, t)` | 用“超时”换算出 deadline | 到点触发取消 | Value 沿父链查 |
| `WithValue(parent, key, val)` | 增加一层 value 包装 | 不改变取消/截止：完全跟着 parent | `Value(key)`：就近覆盖（先查当前层，再向父链找） |


---

## 4) Value
```go
type key int
                     
const (
    userKey key = iota
)

func users(ctx context.Context, req *Request) {
    // 从请求中获取用户信息
    user := req.GetUser
    // 将用户信息保存到 Context 中
    ctx = context.WithValue(ctx, userKey, user)

    // 启动一个 goroutine 来处理请求
    go func(ctx context.Context) {
        // 从 Context 中获取用户信息
        user := ctx.Value(userKey).(*User)

        // 处理请求...
    }(ctx)

}
```

### 4.1 如何向上查找 Value
当你要从上下文里取一个“名字对应的值”时，会按从近到远的顺序找：
先看当前这一层有没有设置；有就直接用。
没有就继续去父上下文找，直到最外层。
如果一路都没找到，就会得到空结果。

### 4.2 如何找最近可取消祖先
Value还有个功能：查找最近可取消祖先。当系统需要把“取消”传给子上下文时，也会向上找一个“负责响应取消的父级”，并且选择离当前最近的那一层。
如果中间某层把取消传递关掉了，这次向上查找就会被截断，子上下文可能就收不到父取消。
提示：普通业务只需关心“取消会沿父链传下去”，不需要自己去用 Value 做“最近可取消祖先”的查询。



---

## 5) Cancel 
取消就是“让一件事停下来”。
它可能来自你手动取消，也可能来自时间到了（截止/超时）。
当父上下文取消后，子上下文会一起进入取消状态，帮助下游停止工作并做收尾。
```go
func users(ctx context.Context, req *Request) {
    // 创建一个可以取消的子 Context 对象（会跟随父级取消）
    childCtx, cancel := context.WithCancel(ctx)

    // 启动一个 goroutine 来处理请求
    go func(c context.Context) {
        // 等待请求完成或者被取消
        select {
        case <-time.After(time.Second):
            // 请求完成
            fmt.Println("Request finish")
        case <-c.Done():
            // 请求被取消
            fmt.Println("Request canceled")
        }
    }(childCtx)

    // 等待一段时间后取消请求
    time.Sleep(time.Millisecond * 800)
    cancel()
}
```



### 5.1 创建可取消的子节点，并接入父链
当你从一个父上下文创建“可取消”的子上下文时：
父级一旦取消，子级也会跟着取消。
你也可以自己手动取消子级，让它立刻停下。

### 5.2 向上查找最近可取消祖先（取消接入时的查找规则）
当你把“子上下文”接到“父上下文”的取消体系里时，系统会找到离你最近的那个“确实能响应取消的父级”，然后把自己接到它那里。

你可以按下面几个直觉理解：
- 父本身不会发生取消事件，子不会因为父而取消。
- 父已经处于取消/截止状态，那么子创建出来时就基本等于“已被取消”（所以你马上就能感知到取消）。
- 父还没取消：系统会继续向上找，直到找到最近的“可取消父级”。找到之后，只要这个父级取消了，子就会跟着一起进入取消状态。
- 父支持回调型的取消接入（也就是父级自己能在取消时执行一段回调），那么父级一取消，就会跑回调，并在回调里把子标记为取消。
- 兜底：无法把 子 挂到父的 children 上，只能起一个 goroutine 等取消



// ----问题----
1. 解释一下context的作用以及它的函数
2. context的Value
3. context的Cancel

// ---goContext---
| 序号 | 上次考试日期 | 上次考试分数 | 下次考试日期 |
| --- | --- | --- | --- |
| 1 | 2026-02-26 | 4.0 | 2026-02-28 |
| 2 | 2026-03-04 | 3.5 | 2026-03-08 |
| 3 | 2026-03-06 | 3.25 | 2026-03-09 |