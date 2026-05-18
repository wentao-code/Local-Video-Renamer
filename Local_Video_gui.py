import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from video_renamer_api import VideoRenamerAPI


class VidNormApp(QWidget):
    def __init__(self):
        super().__init__()
        self.pending_renames = []
        self.csv_path = Path(__file__).with_name('目录统计 - 详细介绍.csv')
        self.api = VideoRenamerAPI(self.csv_path)

        self.load_csv_data()
        self.init_ui()

    def load_csv_data(self):
        try:
            self.api.load_database()
            print(f"成功加载 {len(self.api.video_db)} 条视频元数据")
        except Exception as exc:
            QMessageBox.critical(self, "CSV 加载失败", f"无法读取数据库文件：\n{str(exc)}")

    def init_ui(self):
        self.setWindowTitle('VidNorm - 基于 CSV 数据库的视频规范化工具')
        self.resize(1000, 650)
        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("请选择包含视频的本地文件夹...")
        self.path_input.setReadOnly(True)
        btn_browse = QPushButton('📁 选择文件夹')
        btn_browse.clicked.connect(self.browse_folder)
        top_layout.addWidget(QLabel("本地目录:"))
        top_layout.addWidget(self.path_input)
        top_layout.addWidget(btn_browse)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['原文件名', 'CSV 匹配结果 (规范化)', '匹配状态'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        bottom_layout = QHBoxLayout()
        self.btn_scan = QPushButton('🔍 扫描并匹配 CSV')
        self.btn_scan.clicked.connect(self.scan_files)
        self.btn_execute = QPushButton('🚀 执行重命名')
        self.btn_execute.clicked.connect(self.execute_rename)
        self.btn_execute.setEnabled(False)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_scan)
        bottom_layout.addWidget(self.btn_execute)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.table)
        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder_path:
            self.path_input.setText(folder_path)
            self.table.setRowCount(0)
            self.pending_renames.clear()
            self.btn_execute.setEnabled(False)

    def scan_files(self):
        # ... 前面获取 folder_path 和 plans 的代码保持不变 ...
        # try:
        #     self.pending_renames = self.api.scan_folder(folder_path)
        # ...

        self.table.setRowCount(0)
        has_files_to_rename = False  # 记录是否真的有需要改名的文件

        for row, plan in enumerate(self.pending_renames):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(plan.old_name))
            self.table.setItem(row, 1, QTableWidgetItem(plan.new_name))

            # 👇 核心状态显示逻辑
            if plan.needs_rename:
                status_item = QTableWidgetItem("待重命名")
                status_item.setForeground(Qt.blue)  # 蓝色表示需要操作
                has_files_to_rename = True
            else:
                status_item = QTableWidgetItem("已规范")
                status_item.setForeground(Qt.darkGreen)  # 绿色表示完美状态

            self.table.setItem(row, 2, status_item)

        # 只有在扫描结果不为空，且至少有一个文件需要改名时，才启用“执行重命名”按钮
        self.btn_execute.setEnabled(has_files_to_rename)

        QMessageBox.information(
            self,
            "扫描完成",
            f"共识别到 {len(self.pending_renames)} 个视频，其中有待重命名视频。" if has_files_to_rename else f"共识别到 {len(self.pending_renames)} 个视频，全部符合规范！",
        )
        
    def execute_rename(self):
        results = self.api.execute_renames(self.pending_renames)
        success = 0

        for row, result in enumerate(results):
            status_item = self.table.item(row, 2)
            if result.success:
                status_item.setText("✅ 完成")
                success += 1
            else:
                status_item.setText(f"❌ {result.message}")

        QMessageBox.information(self, "结果", f"成功重命名 {success} 个文件。")
        self.pending_renames.clear()
        self.btn_execute.setEnabled(False)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = VidNormApp()
    window.show()
    sys.exit(app.exec_())
