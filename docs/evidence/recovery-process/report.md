# Recovery benchmark

模型异常、Tool 后退出、append 后退出各 10 次，共 30 次。

从最近一致历史恢复并继续：30/30（100.00%）。

检测到副作用结果不确定：10 次；自动重放：0。成功定义是安全恢复协议状态并能继续，不是 exactly-once 或原任务自动完成。

真实子进程 os._exit 模拟强制退出；模型响应使用离线替身。5 次包含 JSONL 尾部半行。原始日志及失败案例保留于 workspaces 和 fault_injection.csv。
