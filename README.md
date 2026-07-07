# eew-cli-monitor
# 地震预警命令行监控程序

基于 Wolfx , P2PQuake API , NIED , FAN的地震预警命令行工具。程序会每秒轮询一次地震速报数据，当检测到新地震时，会在终端中以彩色表格形式显示详细预警信息（震中、震级、深度、坐标、最大震度/烈度、精度信息等）。

## 支持数据源：

1.wolfx 
- 日本气象厅 (JMA)
- 中国地震台网中心 (CENC)
- 四川地震局 (SC)
- 福建地震局 (FJ)
- 重庆地震局 (CQ)

2.P2PQuake
- 日本气象厅 (JMA)
  
3.NIED
- 日本防灾科学技术研究所(NIED)

4.FAN
- 日本气象厅 (JMA)
- 自然资源部海啸预警中心 (tsunami)
- 中国地震台网地震信息 (cenc)
- 中国地震预警网 (cea)
- 中国地震预警网省级网地震预警 (cea-pr)
- 宁夏自治区地震局地震信息 (ningxia)
- 广西壮族自治区地震局地震信息 (guangxi)
- 山西省地震局地震信息 (shanxi)
- 北京市地震局地震信息 (beijing)
- 云南省地震局地震信息 (yunnan)
- 台湾省气象署地震报告 (cwa)
- 台湾省气象署地震预警 (cwa-eew)
- 香港天文台地震信息 (hko)
- 日本气象厅地震预警 (jma)
- 美国 ShakeAlert 地震预警 (sa)
- 欧洲地中海地震中心地震信息 (emsc)
- 法国中央地震研究所地震信息 (bcsf)
- 德国地学研究中心地震信息 (gfz)
- 巴西圣保罗大学地震信息 (usp)
- 韩国气象厅地震信息 (kma)
- 韩国气象厅地震预警 (kma-eew)
- 韩国气象厅 PEWS 测站实时数据 (kma-station)
- FSSN 地震信息 (fssn)
- FSSN 矩心矩张量解(CMT) (fssn-cmt)

5.FANW
- 中国气象局气象预警(weatheralarm)

![地震预警效果图](./image/image1.png)

## 功能特点

- 每秒检查一次，无新地震时**完全静默**，不影响终端其他操作。
- 新地震触发时**立即弹出彩色表格**。
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
- 解压到任意文件夹（例如 `C:\eew-cli-monitor`）
  
2. 获取第三方库
- 在py文件目录下
- requests>=2.25.0
- rich>=10.0.0
- websocket-client>=1.6.0
```cmd
pip install requests rich websocket-client
```
或
```cmd
pip install -r requirements.txt
```

3. 运行程序
```cmd
python eew-cli-monitor.py
```
4. 退出程序
   
**在命令提示符窗口中按 Ctrl + C 组合键，或直接关闭窗口。**

### 可选：打包成独立可执行文件
- 结构目录
```bash
eew-cli-monitor.py
sounds/
    alert.wav
    nhk_bell.wav
```
- 打包命令
```bash
pyinstaller --onefile --console --add-data "sounds/alert.wav;sounds" --add-data "sounds/nhk_bell.wav;sounds" --exclude-module gevent eew-cli-monitor.py
```
- 生成的可执行文件位于 dist/ 目录，双击即可运行。
  
### 说明

- 本人为高中生，能力有限，项目如有错误请谅解，可以向3822104508@qq.com提交错误,本人会尽力解决
  
### 致谢

- 本程序使用的所有地震预警数据均由 [Wolfx Project](https://wolfx.jp/) , [P2PQuake](https://www.p2pquake.net/) , [NIED](https://www.bosai.go.jp/sp/) , [FAN](https://api.fanstudio.tech/) 提供，感谢他们的无私贡献。
- 感谢 [DeepSeek](https://deepseek.com/) 人工智能助手协助编写、优化和调试本程序代码。
  
### 许可证
- 本项目采用 MIT 许可证。






