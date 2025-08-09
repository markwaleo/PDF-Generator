# -*- coding: utf-8 -*-
"""
PDF工具模块
提供PDF压缩、合并等核心功能
"""

import os
import pikepdf
from pathlib import Path
from typing import List, Optional
import tempfile
import time
import gc


def get_file_size_mb(file_path: str) -> float:
    """获取文件大小（MB）"""
    if os.path.exists(file_path):
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)
    return 0.0


def compress_pdf_with_pikepdf(input_path: str, output_path: str, debug: bool = True) -> bool:
    """
    使用pikepdf进行PDF压缩优化
    
    Args:
        input_path: 输入PDF文件路径
        output_path: 输出PDF文件路径
        debug: 是否输出调试信息
    
    Returns:
        bool: 压缩是否成功
    """
    try:
        # 记录压缩前文件信息
        original_size = get_file_size_mb(input_path)
        start_time = time.time()
        
        # 使用pikepdf进行压缩
        with pikepdf.Pdf.open(input_path) as pdf:
            try:
                # 尝试完整的压缩选项
                pdf.save(
                    output_path,
                    linearize=True,
                    compress_streams=True,
                    stream_decode_level=pikepdf.StreamDecodeLevel.generalized,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                    compress_predictors=True,
                    recompress_flate=True
                )
            except Exception:
                # 如果失败，使用基本压缩选项
                pdf.save(
                    output_path,
                    linearize=True,
                    compress_streams=True,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate
                )
        
        # 清理内存并计算压缩结果
        gc.collect()
        compressed_size = get_file_size_mb(output_path)
        
        if debug:
            compression_ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
            processing_time = time.time() - start_time
            print(f"PDF压缩完成: {os.path.basename(output_path)} ({original_size:.1f}MB -> {compressed_size:.1f}MB, {compression_ratio:.0f}%)")
        
        return True
        
    except Exception as e:
        if debug:
            print(f"PDF压缩失败: {e}")
        return False


def merge_and_compress_pdf(pages: List, output_path: str, temp_dir: Optional[Path] = None, 
                          compress: bool = True, compression_quality: int = 85, 
                          debug: bool = True) -> bool:
    """
    合并图像页面为PDF文件，并根据需要进行压缩
    
    Args:
        pages: 图像页面列表
        output_path: 输出PDF文件路径
        temp_dir: 临时目录路径
        compress: 是否启用压缩功能
        compression_quality: 压缩质量 (1-100)
        debug: 是否输出调试信息
    
    Returns:
        bool: 合并是否成功
    """
    if not pages:
        if debug:
            print("合并失败：没有有效页面")
        return False
    
    # 创建临时工作目录
    if temp_dir is None:
        temp_dir = Path(tempfile.gettempdir()) / "pdf_generator_temp"
    
    temp_dir.mkdir(exist_ok=True)
    temp_pdf_path = temp_dir / "temp_processing.pdf"
    
    try:
        if debug:
            print(f"开始合并 {len(pages)} 个页面{(' (压缩质量: ' + str(compression_quality) + '%)') if compress else ' (无压缩)'}")
        
        start_time = time.time()
        
        # 使用Pillow生成初始PDF
        if compress:
            # 启用压缩模式
            pages[0].save(
                str(temp_pdf_path), 
                save_all=True, 
                append_images=pages[1:] if len(pages) > 1 else [],
                resolution=200.0,
                quality=compression_quality,
                optimize=True
            )
        else:
            # 无压缩模式
            pages[0].save(
                str(temp_pdf_path), 
                save_all=True, 
                append_images=pages[1:] if len(pages) > 1 else [],
                resolution=200.0,
                quality=100,
                optimize=False
            )
        
        gc.collect()
        
        # 根据设置决定是否进行进一步压缩
        if compress:
            success = compress_pdf_with_pikepdf(str(temp_pdf_path), output_path, debug)
        else:
            import shutil
            shutil.copy2(str(temp_pdf_path), output_path)
            success = True
        
        # 清理临时文件
        if temp_pdf_path.exists():
            temp_pdf_path.unlink()
        
        if success and debug:
            final_size = get_file_size_mb(output_path)
            total_time = time.time() - start_time
            print(f"PDF{'合并压缩' if compress else '合并'}完成: {os.path.basename(output_path)} ({final_size:.1f}MB, 耗时{total_time:.1f}s)")
        
        gc.collect()
        
        return success
        
    except Exception as e:
        if debug:
            print(f"PDF合并失败: {e}")
        
        # 确保清理临时文件
        if temp_pdf_path.exists():
            try:
                temp_pdf_path.unlink()
            except:
                pass
        
        gc.collect()
        return False


def cleanup_temp_directory(temp_dir: Path, debug: bool = True):
    """
    清理临时目录及其中的所有文件
    
    Args:
        temp_dir: 临时目录路径
        debug: 是否输出调试信息
    """
    try:
        if temp_dir.exists():
            # 删除目录中的所有文件
            for file_path in temp_dir.glob("*"):
                if file_path.is_file():
                    file_path.unlink()
            
            # 删除空目录
            temp_dir.rmdir()
            if debug:
                print(f"临时目录已清理: {temp_dir.name}")
                
        # 强制垃圾回收
        gc.collect()
                
    except Exception as e:
        if debug:
            print(f"临时文件清理失败: {e}")


if __name__ == "__main__":
    print(f"PDF工具模块 - pikepdf版本: {pikepdf.__version__}")