# 试用书放这里

UI 上的「试用一本」按钮会从这个目录里直接拉 epub 走上传流程，让新用户不用自己出门找一本书就能用上。

## 放什么文件

把仓库根的两本测试 epub 拷过来：

```
web/public/sample/anshi.epub      ← 仓库根的 test安史之乱*.epub
web/public/sample/mingchao.epub   ← 仓库根的 test明朝那些事儿.epub
```

文件名固定就这两个（前端 hard-code 了路径）。

## 为什么不直接入 git

epub 一本 1-3 MB,两本进 git 仓库会让 npm bundle 体积翻倍且每次 clone 都拉一遍。`web/public/sample/*.epub` 已经在 `web/.gitignore` 里。

开发本地、CI、第一次跑 demo 之前手动拷一次就行。

## 文件不在会怎样

按钮还是亮着,点了会拉到 404。前端会跳一段提示告诉用户:

> 试用书还没准备好。请把仓库根的 test 开头的 epub 拷到 `web/public/sample/anshi.epub` 和 `mingchao.epub`,然后刷新页面。
