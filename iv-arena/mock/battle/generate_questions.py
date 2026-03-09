import random
import datetime

# Cloud penetration and encryption questions
questions = [
    "[穿透 序号 1] 为什么需要 NAT 穿透？核心矛盾是什么？",
    "[穿透 序号 2] 穿透/打洞的技术原理（STUN 流程）？",
    "[穿透 序号 3] 项目中完整链路流程（凭证、验证码、接头暗号）？",
    "[穿透 序号 4] 用户层、通道层、内部实现分别用什么？",
    "[穿透 序号 5] STUN、TURN、ICE 分别是什么？",
    "[穿透 序号 6] 怎么得到公网 IP 和端口（原理 vs 我们实现）？",
    "[穿透 序号 7] NAT 类型有哪些，区别？",
    "[穿透 序号 8] P2P 失败云端/整体怎么处理？",
    "[加密 序号 1] 为什么要加密？不加密会怎样（接头暗号被截获）？",
    "[加密 序号 2] 对称加密、非对称加密分别是什么，优缺点？",
    "[加密 序号 3] 哈希算法、数字签名分别用来做什么？",
    "[加密 序号 4] 混合加密的思路和步骤（RSA 传 AES key + AES 加密数据）？"
]

selected = random.sample(questions, 5)

print("好的，我们现在开始“云端”方向的面试（包含穿透、加密）。请回答以下 5 个问题：\n")
for i, q in enumerate(selected, 1):
    print(f"### 第 {i} 题: {q.split('] ')[1]} `{q.split('] ')[0] + ']'}`\n**你的回答**:\n\n---\n")
