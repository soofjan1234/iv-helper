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
        verbose=False,
        fp16=False # macOS 需要关闭 fp16
    )
    
    # 生成带停顿标注的输出
    output_lines = []
    output_lines.append("# 转录结果 (含停顿分析)\n")
    output_lines.append(f"文件: {path.name}\n")
    output_lines.append("---\n\n")
    
    # 带停顿的流式文本
    output_lines.append("## 转录文本 (含停顿)\n\n")
    
    full_text_with_pauses = ""
    last_end = 0.0
    line_char_count = 0
    MAX_LINE_CHARS = 30  # 每行大约 30 个字后折行
    
    for segment in result["segments"]:
        start = segment["start"]
        end = segment["end"]
        text = segment["text"].strip()
        
        # 计算与上一句的间隔（停顿）
        gap = start - last_end
        if gap > 0.3:  # 停顿阈值设置为 0.3 秒
            pause_str = f" [...{gap:.1f}s] "
            full_text_with_pauses += pause_str
            line_char_count += len(pause_str)
        
        # 逐段添加文本
        full_text_with_pauses += text
        line_char_count += len(text)
        
        # 如果当前行字符数超过限制，添加换行符
        if line_char_count >= MAX_LINE_CHARS:
            full_text_with_pauses += "\n"
            line_char_count = 0
            
        last_end = end
    
    output_lines.append(full_text_with_pauses.strip() + "\n\n")
    
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
