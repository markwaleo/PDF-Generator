# -*- coding: utf-8 -*-
"""
工作线程模块
提供后台PDF处理功能，避免界面冻结
"""

import os
import sys
from pathlib import Path
from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal
import gc
import tempfile
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import threading

from pdf2image import convert_from_path
from pdf_utils import merge_and_compress_pdf, cleanup_temp_directory

# 移除PIL图像尺寸限制
Image.MAX_IMAGE_PIXELS = None

class PDFProcessWorker(QThread):
    """
    PDF处理工作线程，在后台处理PDF转换和合并操作
    避免处理大文件时界面冻结
    """
    
    # 信号定义
    progress_updated = pyqtSignal(int, str)  # 进度值和状态信息
    progress_range_updated = pyqtSignal(int)  # 进度范围
    processing_finished = pyqtSignal(bool, str)  # 处理结果和消息
    
    def __init__(self, file_paths, output_path, width, poppler_dir=None, dpi=200, 
                 compress=True, compression_quality=85):
        """
        初始化工作线程
        
        Args:
            file_paths: 要处理的文件路径列表
            output_path: 输出PDF文件路径
            width: 目标图像宽度（像素）
            poppler_dir: poppler工具目录路径
            dpi: PDF转换DPI值
            compress: 是否启用压缩
            compression_quality: 压缩质量 (1-100)
        """
        super().__init__()
        self.file_paths = file_paths
        self.output_path = output_path
        self.width = width
        self.poppler_dir = poppler_dir
        self.dpi = dpi
        self.compress = compress
        self.compression_quality = compression_quality
        self.is_cancelled = False
        
        # 创建临时工作目录
        self.temp_dir = Path(tempfile.gettempdir()) / "pdf_generator_temp"
        self.temp_dir.mkdir(exist_ok=True)
        
        # 获取CPU核心数用于多线程处理
        self.cpu_count = os.cpu_count() or 1
    
    def run(self):
        """主处理流程：计数页面、处理文件、合并PDF"""
        try:
            # 第一阶段：计算总页数
            total_pages = self._count_total_pages()
            if total_pages == 0:
                self.processing_finished.emit(False, "无有效页面")
                return
                
            # 计算进度步数（处理页面 + 保存PDF）
            save_steps = max(1, total_pages // 10)
            total_progress_steps = total_pages + save_steps
            
            self.progress_range_updated.emit(total_progress_steps)
            self.progress_updated.emit(0, f"准备处理 {total_pages} 页...")
            
            # 第二阶段：多线程处理文件
            pages = self._process_files_multithreaded(total_pages, total_progress_steps)
            if not pages or self.is_cancelled:
                if self.is_cancelled:
                    self.processing_finished.emit(False, "操作已取消")
                else:
                    self.processing_finished.emit(False, "处理过程中出错")
                return
            
            # 第三阶段：合并和压缩PDF
            save_start_step = total_pages
            operation_text = "正在合并并压缩PDF文件..." if self.compress else "正在合并PDF文件..."
            self.progress_updated.emit(save_start_step, operation_text)
            
            success = merge_and_compress_pdf(
                pages=pages,
                output_path=self.output_path,
                temp_dir=self.temp_dir,
                debug=False,
                compress=self.compress,
                compression_quality=self.compression_quality
            )
            
            if success:
                completion_text = "PDF合并压缩完成" if self.compress else "PDF合并完成"
                self.progress_updated.emit(total_progress_steps, completion_text)
                result_text = f"PDF 已保存并压缩：{self.output_path}" if self.compress else f"PDF 已保存：{self.output_path}"
                self.processing_finished.emit(True, result_text)
            else:
                self.processing_finished.emit(False, "PDF合并压缩失败" if self.compress else "PDF合并失败")
            
            # 清理临时文件
            cleanup_temp_directory(self.temp_dir, debug=False)
            
        except Exception as e:
            self.processing_finished.emit(False, str(e))
            # 确保清理临时文件
            try:
                cleanup_temp_directory(self.temp_dir, debug=False)
            except:
                pass
    
    def _count_total_pages(self):
        """计算所有文件的总页数"""
        total_pages = 0
        for path in self.file_paths:
            ext = Path(path).suffix.lower()
            if ext in {".png", ".jpg", ".jpeg"}:
                # 图片文件计为1页
                total_pages += 1
            elif ext == ".pdf":
                try:
                    # 使用低 DPI 快速计数PDF页数
                    pdf_imgs = convert_from_path(path, dpi=10, poppler_path=self.poppler_dir)
                    total_pages += len(pdf_imgs)
                except Exception:
                    pass
        return total_pages
    
    def _process_single_file(self, path, page_counter_lock):
        """处理单个文件并返回图像页面列表"""
        result = []
        page_count = 0
        ext = Path(path).suffix.lower()
        
        try:
            if ext in {".png", ".jpg", ".jpeg"}:
                # 处理图片文件
                img = Image.open(path).convert("RGB")
                w_percent = self.width / img.width
                new_height = int(img.height * w_percent)
                img = img.resize((self.width, new_height), Image.Resampling.LANCZOS)
                result.append(img)
                page_count = 1
                
            elif ext == ".pdf":
                # 处理PDF文件
                pdf_pages = convert_from_path(
                    path, dpi=self.dpi,
                    poppler_path=self.poppler_dir if self.poppler_dir else None
                )
                
                for pg in pdf_pages:
                    if self.is_cancelled:
                        return [], 0
                    
                    pg = pg.convert("RGB")
                    w_percent = self.width / pg.width
                    new_height = int(pg.height * w_percent)
                    pg = pg.resize((self.width, new_height), Image.Resampling.LANCZOS)
                    result.append(pg)
                    page_count += 1
                    
                    # 定期清理内存
                    if page_count % 10 == 0:
                        gc.collect()
        except Exception:
            return [], 0
            
        return result, page_count
    
    def _process_files_multithreaded(self, total_pages, total_progress_steps):
        """使用多线程并行处理所有文件"""
        result = []
        processed_pages = 0
        
        # 计算最优线程数
        max_workers = min(self.cpu_count, len(self.file_paths))
        page_counter_lock = threading.Lock()
        
        # 使用线程池并行处理文件
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self._process_single_file, path, page_counter_lock): path 
                for path in self.file_paths
            }
            
            # 处理完成的任务
            for future in concurrent.futures.as_completed(future_to_path):
                if self.is_cancelled:
                    # 取消所有未完成的任务
                    for f in future_to_path:
                        f.cancel()
                    return []
                
                path = future_to_path[future]
                try:
                    pages, page_count = future.result()
                    result.extend(pages)
                    processed_pages += page_count
                    
                    current_progress = min(processed_pages, total_pages)
                    self.progress_updated.emit(current_progress, f"已处理 {processed_pages}/{total_pages} 页")
                    
                except Exception:
                    current_progress = min(processed_pages, total_pages)
                    self.progress_updated.emit(current_progress, f"处理文件失败: {Path(path).name}")
        
        return result
    
    def cancel(self):
        """设置取消标志，停止当前处理"""
        self.is_cancelled = True