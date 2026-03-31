// ----资料----
Context 用来在 API 边界和进程之间传递：

- **截止时间（deadline）**
- **取消信号（cancellation）**
- **请求范围内的数据（request-scoped values）**

## 结构

```go
type Context interface {
	// 返回这个 context 的截止时间（到了这个时间就该取消）
	 Deadline() (deadline time.Time, ok bool)
	 // 返回一个只读 channel，当这个 context 被取消时，该 channel 会被 close
	 Done() <-chan struct{}
	 // 说明为什么这个 context 被取消了
	 Err() error
	 // 从当前 context 及其父链上查找与 key 关联的值；找不到返回 nil
	 Value(key any) any
}
```

在 Go 的 `context` 包中，`Background`、`TODO` 和 `emptyCtx` 是整个上下文树的起点或根基

| **名称** | **类型** | **语义（Semantics）** |
| --- | --- | --- |
| `context.Background()` | `emp              tyCtx` | **“我明确知道这就是根”**。用于 `main` 函数、初始化或测试代码。 |
| `context.TODO()` | `emptyCtx` | **“我暂时不知道该传什么”**。用于代码重构或 API 设计时，占个位子。 |
| `emptyCtx` | 底层私有类型 | 上述两者的**底层实现**（一个不可变的空结构体）。 |

## WithValue

### 用法

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

### 源码

```go
func WithValue(parent Context, key, val any) Context {
	if parent == nil {
		panic("cannot create context from nil parent")
	}
	if key == nil {
		panic("nil key")
	}
	if !reflectlite.TypeOf(key).Comparable() {
		panic("key is not comparable")
	}
	return &valueCtx{parent, key, val}
}

type valueCtx struct {
	Context
	key, val any
}
```

查找：

1. 先看自己，再问父
2. 当前层没有，往父走
3. 到根了，没有就是没有
4. 用户自定义的 Context，自己查

有一种**特殊的内部 Key** 叫 `cancelCtxKey`。它的作用不是存取用户数据，而是**在 Context 树中向上寻找最近的一个“可取消的祖先”**

```go
func (c *valueCtx) Value(key any) any {
	if c.key == key {
		return c.val
	}
	return value(c.Context, key)
}

func value(c Context, key any) any {
	for {
		switch ctx := c.(type) {
		case *valueCtx:
			if key == ctx.key {
				return ctx.val
			}
			c = ctx.Context // 当前层没有，往父走
		// 这三个case都是为了寻找最近的一个“可取消的祖先”
		case *cancelCtx:
			// **寻找最近的一个“可取消的祖先”**
			if key == &cancelCtxKey {
				return c
			}
			c = ctx.Context
		case withoutCancelCtx:
			// 不传播取消的包装
			if key == &cancelCtxKey {
				// This implements Cause(ctx) == nil
				// when ctx is created using WithoutCancel.
				return nil
			}
			c = ctx.c
		case *timerCtx:
			// timerCtx 内嵌了 cancelCtx
			// 真正负责 children、Done()、cancel() 的是里面的 cancelCtx
			if key == &cancelCtxKey {
				return &ctx.cancelCtx
			}
			c = ctx.Context
		case backgroundCtx, todoCtx: 
			return nil // 到根了，没有就是没有
		default:
			 // 用户自定义的 Context，不在这里展开，直接 return c.Value(key)，让自定义实现自己查
			return c.Value(key)
		}
	}
}
```

## WithCancel

**Context 的 Value 只用来传“请求范围”的数据**（跨进程、跨 API），不要拿来当普通可选参数用。

### 用法

```go
func users(ctx context.Context, req *Request) {
    // 创建一个可以取消的 Context 对象
    ctx, cancel := context.WithCancel(ctx)

    // 启动一个 goroutine 来处理请求
    go func(ctx context.Context) {
        // 等待请求完成或者被取消
        select {
        case <-time.After(time.Second):
            // 请求完成
            fmt.Println("Request finish")
        case <-ctx.Done():
            // 请求被取消
            fmt.Println("Request canceled")
        }
    }(ctx)

    // 等待一段时间后取消请求
    time.Sleep(time.Millisecond * 800)
    cancel()
}
```

### 源码

```go
// WithCancel / WithDeadline / WithTimeout：
// 接收一个父 Context，返回子 Context 和一个 CancelFunc
func WithCancel(parent Context) (ctx Context, cancel CancelFunc) {
	c := withCancel(parent)
	return c, func() { c.cancel(true, Canceled, nil) }
}
```

propagateCancel：把当前这个 **child**（实现了 canceler 的 context）挂到 **parent** 上，并安排好「parent 被取消时去取消 child」

1. 父永远不会被取消，直接返回
2. 父已经取消了，直接取消child
3. 父是 cancelCtx（或内层是 cancelCtx），挂到父的 children
4. 父支持 AfterFunc，说明父可以在「自己被取消时」跑一个回调，将取消函数加到回调
5. 父是“别的类型”（通用兜底），无法把 child 挂到父的 children 上，只能起一个 goroutine等取消

```go
func withCancel(parent Context) *cancelCtx {
	if parent == nil {
		panic("cannot create context from nil parent")
	}
	c := &cancelCtx{}
	c.propagateCancel(parent, c)
	return c
}

func (c *cancelCtx) propagateCancel(parent Context, child canceler) {
	c.Context = parent

	// 分支1
	done := parent.Done()
	if done == nil {
		return // parent is never canceled
	}

	// 分支2
	select {
	case <-done:
		// parent is already canceled
		child.cancel(false, parent.Err(), Cause(parent))
		return
	default:
	}

	// 分支3
	if p, ok := parentCancelCtx(parent); ok {
		// parent is a *cancelCtx, or derives from one.
		p.mu.Lock()
		if err := p.err.Load(); err != nil {
			// parent has already been canceled
			child.cancel(false, err.(error), p.cause)
		} else {
			if p.children == nil {
				p.children = make(map[canceler]struct{})
			}
			p.children[child] = struct{}{}
		}
		p.mu.Unlock()
		return
	}
	
	// 分支4
	if a, ok := parent.(afterFuncer); ok {
		// parent implements an AfterFunc method.
		c.mu.Lock()
		stop := a.AfterFunc(func() {
			child.cancel(false, parent.Err(), Cause(parent))
		})
		c.Context = stopCtx{
			Context: parent,
			stop:    stop,
		}
		c.mu.Unlock()
		return
	}

	// 分支5
	goroutines.Add(1)
	go func() {
		select {
		case <-parent.Done():
			child.cancel(false, parent.Err(), Cause(parent))
		case <-child.Done():
		}
	}()
}
```

上面的propagateCancel是cancelCtx实现的方法

```go
// A cancelCtx can be canceled. When canceled, it also cancels any children
// that implement canceler.
type cancelCtx struct {
	Context

	mu       sync.Mutex            // protects following fields
	done     atomic.Value          // of chan struct{}, created lazily, closed by first cancel call
	children map[canceler]struct{} // set to nil by the first cancel call
	err      atomic.Value          // set to non-nil by the first cancel call
	cause    error                 // set to non-nil by the first cancel call
}

// 关 channel、设 err、递归取消所有 children、从 parent 里移除自己
func (c *cancelCtx) cancel(removeFromParent bool, err, cause error) {
	...
}
```

上文说的用value来**寻找最近的一个“可取消的祖先”**

```go
func parentCancelCtx(parent Context) (*cancelCtx, bool) {
	done := parent.Done()
	if done == closedchan || done == nil {
		return nil, false
	}
	p, ok := parent.Value(&cancelCtxKey).(*cancelCtx)
	if !ok {
		return nil, false
	}
	pdone, _ := p.done.Load().(chan struct{})
	if pdone != done {
		return nil, false
	}
	return p, true
}
```

## WithDeadline、WithTimeout

设置截止时间、设置超时时间

```go
ctx, cancel := context.WithDeadline(ctx, time.Now().Add(time.Second))
ctx, cancel := context.WithTimeout(ctx, time.Second)
```

### 源码

```go
func WithDeadline(parent Context, d time.Time) (Context, CancelFunc) {
	return WithDeadlineCause(parent, d, nil)
}

func WithTimeout(parent Context, timeout time.Duration) (Context, CancelFunc) {
	return WithDeadline(parent, time.Now().Add(timeout))
}

func WithDeadlineCause(parent Context, d time.Time, cause error) (Context, CancelFunc) {
	if parent == nil {
		panic("cannot create context from nil parent")
	}
	if cur, ok := parent.Deadline(); ok && cur.Before(d) {
		// The current deadline is already sooner than the new one.
		return WithCancel(parent)
	}
	c := &timerCtx{
		deadline: d,
	}
	c.cancelCtx.propagateCancel(parent, c)
	dur := time.Until(d)
	if dur <= 0 {
		c.cancel(true, DeadlineExceeded, cause) // deadline has already passed
		return c, func() { c.cancel(false, Canceled, nil) }
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.err.Load() == nil {
		c.timer = time.AfterFunc(dur, func() {
			c.cancel(true, DeadlineExceeded, cause)
		})
	}
	return c, func() { c.cancel(true, Canceled, nil) }
}

```

// ----问题----
1. 解释一下context的作用
2. 讲一下context.WithValue
3. 讲一下context.WithCancel
4. 讲一下context.WithDeadline, WithTimeout

// ---goContext---
| 序号 | 上次考试日期 | 上次考试分数 | 下次考试日期 |
| --- | --- | --- | --- |
| 1 | 2026-02-26 | 4.0 | 2026-02-28 |
| 2 | 2026-03-04 | 3.5 | 2026-03-08 |
| 3 | 2026-03-06 | 3.25 | 2026-03-09 |
| 4 |