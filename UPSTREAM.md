# 上游来源

本项目采用 `wanghao6736/BH_CGYY` 的 CLI 核心，固定版本：

- 仓库：https://github.com/wanghao6736/BH_CGYY
- Commit：`19b1687c1be7fd64fd86808908048efada201f81`（2026-06-17）
- 原许可证：MIT，保留于 `LICENSE`
- 原说明：`README.upstream.md`

本地版本保留 `src/` 中的接口、登录、验证码及订单逻辑。未打包上游桌面 UI、图标或构建脚本。
新增 `buaa_booking/` 和 Windows 启动脚本。调整通用 HTTP 重试策略、请求超时，以及 Windows 中文字体路径。

定时预热、演练和补抢的设计还参考了：
https://github.com/YosinLiu/buaa-venue-helper-2 。未复制该仓库源代码。

上游部分测试依赖其仓库未附带的 `docs/responses` 样本。本地验收运行 `tests/`，以及选定的无需私人样本的上游回归测试。
