"""
语音转文字脚本 - 使用 Whisper
使用方法: python transcribe.py 录音文件.m4a
输出: 同名 .txt 文件（带时间戳）
"""

import sys
import whisper
from pathlib import Path
import glob

def transcribe(audio_path: str):
    """转录音频文件，输出带时间戳的文本"""
    # 支持通配符
    if "*" in audio_path:
        matches = glob.glob(audio_path)
        if matches:
            audio_path = matches[0]
            print(f"找到文件: {audio_path}")
    
    path = Path(audio_path)
    if not path.exists():
        print(f"文件不存在: {audio_path}")
        return
    
    print(f"正在加载 Whisper 模型...")
    model = whisper.load_model("base")  # 可选: tiny, base, small, medium, large
    
    print(f"正在转录: {audio_path}")
    result = model.transcribe(
        str(path),
        language="zh",
        word_timestamps=True,
        verbose=False
    )
    
    # 生成带时间戳的输出
    output_lines = []
    output_lines.append("# 转录结果\n")
    output_lines.append(f"文件: {path.name}\n")
    output_lines.append("---\n\n")
    
    # 完整文本
    output_lines.append("## 完整文本\n\n")
    output_lines.append(result["text"].strip() + "\n\n")
    
    # 分段文本（带时间戳）
    output_lines.append("## 分段详情\n\n")
    for segment in result["segments"]:
        start = segment["start"]
        end = segment["end"]
        text = segment["text"].strip()
        # 计算停顿（与上一段的间隔）
        output_lines.append(f"[{start:.1f}s - {end:.1f}s] {text}\n")
    
    # 保存文件
    output_path = path.with_suffix(".txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(output_lines)
    
    print(f"转录完成: {output_path}")
    return output_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python transcribe.py <音频文件>")
        sys.exit(1)
    
    transcribe(sys.argv[1])
