#!/bin/bash

# 设置环境名称
ENV_NAME="iv-helper-speech"

# 1. 检查并创建 Conda 环境
if conda info --envs | grep -q "$ENV_NAME"; then
    echo "✅ 环境 $ENV_NAME 已检测到。"
else
    echo "📦 正在创建 Conda 环境: $ENV_NAME (Python 3.10)..."
    conda create -n "$ENV_NAME" python=3.10 -y
    
    # --- 环境初始化步骤 (仅首次执行) ---
    # 2. 移除 conda 版 ffmpeg (使用系统 brew installed 版，避免库冲突)
    echo "🧹 正在移除 Conda ffmpeg (以解决库冲突，优先使用 brew 版)..."
    conda remove -n "$ENV_NAME" ffmpeg -y

    # 3. 安装 nomkl (防止 Intel MKL 冲突导致 Segfault)
    echo "🔧 正在安装 nomkl (macOS 修复)..."
    conda install -n "$ENV_NAME" nomkl -y
fi

# 4. 安装/更新 Python 依赖 (Pip check 很快，保留在此处以防 requirements 变动)
echo "⬇️  正在检查 Python 依赖..."
conda run -n "$ENV_NAME" pip install -r requirements.txt

# 5. 运行转录脚本
echo "🚀 正在运行转录 (目标: output.m4a)..."

# 修复 macOS 上常见的 OpenMP 库冲突错误 (OMP: Error #15)
export KMP_DUPLICATE_LIB_OK=TRUE

# 检查是否有 output.m4a，如果没有则提示
if [ -f "output.m4a" ]; then
    conda run -n "$ENV_NAME" python transcribe.py output.m4a
else
    echo "⚠️  当前目录下未找到 output.m4a。你可以使用以下命令手动运行："
    echo "conda run -n $ENV_NAME python transcribe.py <你的音频文件>"
fi
