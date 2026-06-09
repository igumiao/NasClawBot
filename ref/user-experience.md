User Experience and Random Thoughts

This document is  created by the owner of this project to track some random thoughts and the user experience. These general thoughts are for  improving the project in general but some of them are not necessary important. As an agent, u don't need to read this document unless I specifically mentioned it.



1. 可以增加的Tool:

   2. 网络测速工具，可以通过历史下载速度去预估这个种子的下载速度 ？

   3. 文件操作 影视资源管理 注意NAS是飞牛os也就是debian系统 可能有linux MCP这类东西


2. 搜索质量差参差不齐 
   2. imdb id 可以很好去搜索单一资源 但对于电视剧又有季 又有集就不是很好 因为mteam种子的上传是人为的 有些人选择了例如克拉克森第五季的第一季imdb id作为信息上传 有些则是以这个克拉克森的农场这个系列 上传信息 所以还是以名字优先选择 llm通过名字取判断信息 因为种子名字信息还是很规范的
   3. mteam search mode范围不够全 会有很多遗漏 根据我们的实验 我们搜索星球大战 用mode=normal/tvhsow/movie 之前有些差距 例如 我想看最新的动画tvshow 星球大战达斯摩尔 他又是动画 又是tvshow 两个都对 但是这种标签是人为标记的 会有歧义 所以 我们可能得做一些调整 例如normal（快速看一眼）+ movie（补电影）+ tvshow（补剧集）或者直接放弃mode 一切都以normal 
   4. 总而言之 我的意思是 应该让LLM 原本通过mteam api arg的去筛选 在一些情况下不好用 这是mteam的问题 不是我们的问题 但是我们只能去迎合 所以我的想法是让llm 多看到一些candidate去判断 
   

3. 对话目的过于局限性 现在我问一些笼统的问题似乎也不行 可能原因是工具太少，prompt过于局限性

   1. 增加网页搜索能力
   2. prompt扩展
   4. 判断是否引入多Agent

4. 工具搜索使用的args展示不清楚 无法很好的判断/追踪 是否正确调用了我们所预期的args

5. 需要多引入Agent评估模块所需的内容

6. 避开开发功能全 逐渐追求高工程化 例如 高并发， 异步，Agent本身有很多请求调动，这方面可以多做一些后端工程化的思考。

   是否引入redis，mq或者其他中间件 传统后端企业化开发思维也要往项目放 不用多 虽然使用范围少 不能实现高点击 但也需要尝试去测试

7. 