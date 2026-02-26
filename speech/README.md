# 语音/视频转文字工具 (Whisper)

这个工具用于将录音或视频文件转录为带停顿标注和自动换行的文本文件，特别适合用于面试后的自我复盘。

## 核心功能
*   **多格式支持**：支持 `.m4a`, `.mp3`, `.wav`, `.mp4`, `.mov` 等音视频格式。
*   **停顿分析**：自动识别话语中的空白时间，并在文本中插入 `[...0.5s]` 标记。
*   **自动换行**：每行限制约 30 个字，使文本结构清晰。
*   **高精度**：使用 OpenAI Whisper (Base) 模型进行中文转录。

## 环境准备 (首次使用)
工具依赖 `conda` 环境和 `ffmpeg`。

1.  **安装 FFmpeg** (如果未安装):
    ```bash
    brew install ffmpeg
    ```

2.  **创建 Conda 环境**:
    可以运行 `sh run_with_conda.sh` 自动初始化（如果该脚本可用），或者手动创建：
    ```bash
    conda create -n iv-helper-speech python=3.10 -y
    conda activate iv-helper-speech
    pip install -r requirements.txt
    ```

## 使用方法

### 1. 简单用法 (直接使用 Python)
如果你已经激活了环境：
```bash
python transcribe.py <你的文件路径>
```

### 2. 通过 Conda 运行 (推荐)
无需手动切换环境，直接执行：
```bash
export KMP_DUPLICATE_LIB_OK=TRUE  # macOS 必填，防止 OpenMP 报错
conda run -n iv-helper-speech python transcribe.py /path/to/your/video.mp4
```

### 3. 先提取音频再转录 (处理超大视频推荐)
如果视频非常大，可以手动先提取音频提速：
```bash
ffmpeg -i input_video.mp4 -vn -ar 16000 -ac 1 -y temp_audio.m4a
conda run -n iv-helper-speech python transcribe.py temp_audio.m4a
```

## 输出结果说明
转录完成后，会在同一目录下生成一个同名的 `.txt` 文件：

> **示例内容：**
> 我刚才提到的那个项目 [...0.5s] 主要是在做穿透。
> 它的原理是基于 NAT 映射表的原理。
> [...1.2s] 面试官问我为什么要用这个技术...

## 配置调整 (transcribe.py)
*   **调整换行字数**：修改 `MAX_LINE_CHARS = 30`。
*   **调整停顿阈值**：修改 `if gap > 0.3:`。
*   **调整模型精度**：修改 `model = whisper.load_model("base")` (可选: `tiny`, `small`, `medium`)。
