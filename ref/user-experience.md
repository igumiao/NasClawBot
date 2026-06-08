User Experience and Random Thoughts

This document is  created by the owner of this project to track some random thoughts and the user experience. These general thoughts are for  improving the project in general but some of them are not necessary important. As an agent, u don't need to read this document unless I specifically mentioned it.



1. 可以增加的Tool:

   1. qbitorrent应该可以有更多的操作能力 更改下载位置

   2. 网络测速工具，可以通过历史下载速度去预估这个种子的下载速度

   3. 文件操作 影视资源管理 注意NAS是飞牛os也就是debian系统 可能有linux MCP这类东西

   4. 豆瓣imdb

   5. 

2. 搜索质量差， 主要问题在于搜索的api只能接受单个key然后 tool强行缩减到5个candidate，对于llm只能看到5个候选。一部影视作品可能需要多个关键词去搜索，例如克拉克森的农场 现在有第五季，keyword可以是 ”克拉克森农场 第五季“ “Clarkson's Farm” “Clarksons Farm” （有没有带 ‘ 似乎不重要）第五季可以是S05 s5 or Season 5， 由于mteam搜索对于关键词的判断不属于我们可以控制的范围，所以可以有如下想法：

   1. 如果单次搜索没有结果 应该多次搜索
   2. 利用豆瓣imdb资源去搜索 需要增加工具

3. 对话目的过于局限性 现在我问一些笼统的问题似乎也不行 可能原因是工具太少，prompt过于局限性

   1. 增加网页搜索能力
   2. 接入imdb或者豆瓣
   3. prompt扩展
   4. 判断是否引入多Agent

4. 工具搜索使用的args展示不清楚 无法很好的判断/追踪 是否正确调用了我们所预期的args

5. 需要多引入Agent评估模块所需的内容

6. 避开开发功能全 逐渐追求高工程化 例如 高并发， 异步，Agent本身有很多请求调动，这方面可以多做一些后端工程化的思考。

   是否引入redis，mq或者其他中间件 传统后端企业化开发思维也要往项目放 不用多 虽然使用范围少 不能实现高点击 但也需要尝试去测试

7. 