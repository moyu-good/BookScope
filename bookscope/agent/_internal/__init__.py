"""``bookscope.agent._internal`` —— Sprint 7 步骤 ③a 引入的内部共享层。

定位：r1 / r2 loop 与 adapter 之间真重复使用的常量 / helper 的物理归属
地。Sprint 7 ③b 真删 r1 物理文件之前，本层让 r2 的 import 链不再指向
``bookscope.agent.loop`` / ``bookscope.agent.adapters.deepseek`` /
``bookscope.agent.adapters.anthropic``——③b 时 r1 文件 ``git rm`` 不再
牵连 r2。

不是公共 API——下划线前缀模块名表明本层服务于本包内部 r1 / r2 双轨期
解耦，外部代码请勿 import。Sprint 7 ③b 落地后本层将进入"r2 内部 helper"
长期归属，模块名保留下划线以提示语义。
"""
