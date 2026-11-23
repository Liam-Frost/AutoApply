# 岗位来源、入库条件与去重

## 来源

| 来源 | 怎么读 | 自动 | 备注 |
| --- | --- | --- | --- |
| Amazon | amazon.jobs 的搜索接口 | 是 | 带完整岗位说明 |
| Apple | jobs.apple.com 搜索接口 + 详情接口 | 是 | |
| Google | 招聘页 HTML 里内嵌的数据 | 是 | 页面结构变了需要改解析 |
| Microsoft | apply.careers.microsoft.com（Eightfold） | 是 | 请求太快会被限流，已放慢 |
| NVIDIA | nvidia.eightfold.ai（Eightfold） | 是 | |
| AMD | careers.amd.com 接口 | 是 | |
| Intel | Workday（intel.wd1） | 是 | Workday 维护期间读不到 |
| Meta | 没有公开接口，用普通无头浏览器读渲染后的页面 | 是 | 慢，一次约 10 分钟；被拒绝访问时会如实报错，不做伪装 |
| Greenhouse / Ashby / Lever / Workday 看板 | 各自的公开接口 | 是 | 在“岗位 → 来源与关注雇主”里添加公司 |
| UBC PD Portal | 由 Agent 登录并读取（用保存的登录名和密码，手机上的二次验证由你批准；建议用 nodriver 后端）；也可用书签脚本导入 | 是 | Agent 登录不了时（没有保存密码、你没批准）待办里会请你登录 |

代码：`backend/autoapply/sources/bigtech.py`、`sources/public.py`、`sources/pdportal_import.js`。

大厂官网按设置里的搜索词（“设置 → 求职目标与匹配 → 在大型官网上搜什么”；第一次运行的向导按求职阶段填好，实习是 `intern`、`co-op`；一个都没有时用 `intern`）各搜一遍，每个词最多取 200 条。

## 入库条件

`backend/autoapply/intake.py`。每读到一个岗位，先用标题和地点做便宜的文字判断，不符合的不入库、不评分：

1. 标题里有“岗位类型”词之一（intern、co-op…）
2. 标题里有“方向”词之一（software、engineer…）
3. 标题里没有排除词（senior、manager、PhD…）
4. 地点在选定的国家（没写地点不丢）
5. 发布时间在 N 天内（没写日期不丢）

PD Portal 和手动添加的岗位不过滤。留下来的岗位再由模型读全文评分；每次最多评 `scoring.max_per_run` 个，其余下次再评。

大厂官网的列表是截断过、筛选过的，所以不用“这次没出现就算下线”，而是连续 5 天没再出现才标为下线。

## 同一个岗位出现在两个来源

`discover.link_duplicates()`，每次扫描或导入后运行。两条记录满足任一条件就算同一个岗位：

- 申请链接相同（去掉跟踪参数后比较）；
- 公司名和岗位名相同（去掉 Inc、Corporation 等后缀，忽略大小写和标点），学期也相同，并且来自不同来源。

同一来源里标题相同的两条不合并（大厂常有同名但不同组的岗位）。

合并后留一条主记录：已经投过的优先，其次是 PD Portal 那条（它带截止时间和 co-op 办公室要求的材料），再其次是先入库的。其余记录标记为“重复”，不出现在列表里，不评分、不生成草案。主记录会补上官网的申请链接、更完整的岗位说明、地点和薪资。岗位详情里会写明“在别处也出现了”。

已知局限：PD Portal 上的标题和官网标题措辞不同、链接也不同的时候，认不出是同一个岗位，会留成两条。
