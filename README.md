# eew-cli-monitor
# 地震预警命令行监控程序

基于 Wolfx 公益 API 的地震预警命令行工具。程序会每秒轮询一次地震速报数据，当检测到新地震时，会在终端中以彩色表格形式显示详细预警信息（震中、震级、深度、坐标、最大震度/烈度、精度信息等）。

支持数据源：
- 日本气象厅 (JMA)
- 中国地震台网中心 (CENC)
- 四川地震局 (SC)
- 福建地震局 (FJ)
- 重庆地震局 (CQ)

![地震预警效果图](./image/image1.png)

## 功能特点

- 每秒检查一次，无新地震时**完全静默**，不影响终端其他操作。
- 新地震触发时**立即弹出美观的彩色表格**。
- 每个地震只提醒一次（基于事件ID去重）。
- 支持显示坐标、最大震度（日本）或最大烈度（中国）、震源深度、精度信息、警报区域示例等。
- 可灵活启用/禁用任意数据源。
- 可打包成独立 `.exe` 文件，双击即可运行。

## 环境要求

- Python 3.7 或更高版本
- 网络连接（用于访问 Wolfx API）

## 安装步骤
 
### 自动安装

下载最新发行版

### 手动安装
1. 获取程序代码

- 访问本仓库页面
- 点击绿色的 **Code** 按钮 → **Download ZIP**
- 解压到任意文件夹（例如 `C:\earthquake`）
  
2. 获取第三方库
- 在py文件目录下
- requests>=2.25.0
- rich>=10.0.0
```cmd
pip install requests rich
```
3. 运行程序
```cmd
python earthquake_monitor.py
```
4. 退出程序
   
**在命令提示符窗口中按 Ctrl + C 组合键，或直接关闭窗口。**

### 可选：打包成独立可执行文件
- 结构目录
```bash
earthquake_monitor.py
sounds/
    alert.wav
    nhk_bell.wav
```
- 打包命令
```bash
pyinstaller --onefile --console --add-data "sounds/alert.wav;sounds" --add-data "sounds/nhk_bell.wav;sounds" --exclude-module gevent earthquake_monitor.py
```
- 生成的可执行文件位于 dist/ 目录，双击即可运行。
  
### 说明

- 本人为高中生，能力有限，项目如有错误请谅解，可以向3822104508@qq.com提交错误,本人会尽力解决
  
### 致谢

- 本程序使用的所有地震预警数据均由 [Wolfx Project](https://wolfx.jp/) 公益提供，感谢他们的无私贡献。
- 感谢 [DeepSeek](https://deepseek.com/) 人工智能助手协助编写、优化和调试本程序代码。
  
### 许可证
- 本项目采用 MIT 许可证。






