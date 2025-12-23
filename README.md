# 🎯 资金盘推演 - Trading Simulation

加密货币交易风险管理与策略推演工具 - 专业级仓位管理与强平风险分析

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://your-app-url.streamlit.app)

## ✨ 核心功能

### 📊 实时市场数据
- 实时BTC价格（CoinGecko API，无地理限制）
- 自动价格刷新与缓存优化

### 💰 双平台资金管理
- **Binance 合约** (10x杠杆)
  - 独立全仓模式模拟
  - 实时强平价计算
  - 维持保证金率监控
  
- **Luno 现货** (1x，无杠杆)
  - 现货持仓管理
  - 无强平风险

### 💸 智能资金划转
- Luno ↔ Binance 双向划转
- 实时影响预览
  - 强平价变化
  - 风险缓冲率
  - 安全性检查
- 划转历史记录
- 一键清空历史

### 🎯 操作序列模拟
- 多步骤买卖操作
- 百分比/固定金额支持
- 双平台独立操作
- 实时余额追踪
- 可滚动操作列表
- 一键删除操作

### 📈 目标价推演
- **情景A**: Hold策略（基准对比）
- **情景B**: 操作序列执行效果
- 清晰的收益对比
- 百分比/绝对值显示

### 📊 策略可视化
- 交互式PnL曲线图
- Hold vs 操作序列对比
- 操作点标记
- 强平线警示
- 现货持仓价值追踪

## 🚀 本地运行

```bash
# 克隆仓库
git clone https://github.com/Young1290/tradingSimulation.git
cd tradingSimulation

# 安装依赖
pip install -r requirements.txt

# 运行应用
streamlit run Calculation.py
```

访问 `http://localhost:8501`

## ☁️ 在线部署

### Streamlit Community Cloud（推荐）

1. Fork 本仓库到您的GitHub账号
2. 访问 [Streamlit Community Cloud](https://streamlit.io/cloud)
3. 使用GitHub账号登录
4. 点击 "New app"
5. 选择您的仓库和分支
6. Main file path: `Calculation.py`
7. 点击 "Deploy"

### 其他部署选项
- Heroku
- AWS/Google Cloud
- 任何支持Python的云平台

## 📋 技术栈

- **Frontend**: Streamlit
- **数据处理**: Pandas, NumPy
- **可视化**: Plotly
- **API**: CoinGecko (实时价格)

## 📁 项目结构

```
tradingSimulation/
├── Calculation.py          # 主应用
├── transfer_engine.py      # 资金划转引擎
├── ui_components.py        # UI组件
├── ui_styles.py           # 样式定义
├── requirements.txt       # 依赖
└── README.md             # 说明文档
```

## 🎨 主要改进

### v2.0 (2025-12)
- ✅ 双平台支持（Binance + Luno）
- ✅ 智能资金划转系统
- ✅ 滚动位置保持
- ✅ 操作序列实时计算
- ✅ 目标价情景对比
- ✅ 策略图表优化

### v1.0 (2025-11)
- ✅ 基础风险计算
- ✅ 强平价监控
- ✅ 简单操作序列

## 📝 使用说明

### 1. 编辑当前状态
在侧边栏输入当前持仓、价格和资金信息

### 2. 资金划转（可选）
在"💸 资金划转"区执行Luno与Binance之间的资金转移

### 3. 添加操作序列
在"🔶 Binance"或"🟦 Luno"标签下添加计划的买卖操作

### 4. 查看推演结果
- **操作序列**: 实时查看每步操作后的状态
- **目标价推演**: 对比Hold vs 操作策略
- **策略图**: 可视化PnL曲线

## ⚠️ 免责声明

本工具仅供教育和模拟目的。不构成投资建议。
加密货币交易存在高风险，请谨慎决策。

## 📧 联系方式

- GitHub: [@Young1290](https://github.com/Young1290)
- Issues: [提交问题](https://github.com/Young1290/tradingSimulation/issues)

## 📄 License

MIT License - 详见 LICENSE 文件

---

**⭐ 如果这个项目对您有帮助，请给一个Star！**
