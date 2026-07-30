在这个项目中，我们一起构建一个美股财报分析问答Agent，以美股10-K/10-Q财报为数据源，**Agentic RAG** 为检索方式，**Loop**为Agent架构，代码保持**极简**。这是一个**教学性质**的项目，所以每行代码，每个方法都要有它的作用，并有详细的中文注释。每一个阶段的实现都要详细的写文档：你做了什么，怎么实现的，做出了什么决定，是什么原因。项目初始目录里只提供了一个mcp server，功能是输入公司名/年份/10-K/10-Q获取清洗后的财报原文。项目原生支持多轮对话，流式输出，以TUI作为前端。

# 实现步骤：
1. 实现一个支持mcp，工具调用，多轮对话的极简Agent Loop
2. 实现检索功能：
    - 检索之前先按元数据过滤
    - 结构感知的文档切块，并且实现Contextual Retrieval（Anthropic提出的方法），在每个chunk前写一句规则生成的chunk描述。
    - LanceDB作为向量数据库，本机hf缓存里有bge-m3 embedding模型
    - 本机hf缓存里还有bge-reranker
3. Tools
   1. 检索tool，把检索作为tool让Agent loop调用，这是Agentic RAG的Agentic之处。tool description里应该有让模型改写查询的要求。
   2. 计算tool。在session中维护一个REPL金融计算环境，只提供基础运算符但是数据类型应该是decimal不是float。这个tool要让模型能够使用这个计算环境。
   3. 请求用户澄清tool。让模型在需要从用户处获取额外信息时调用，并在TUI上呈现交互。
4. Evaluation：自建30条模拟用户交互的评测集，覆盖多轮场对话，涉及多公司，计算，澄清等各种场景，最终得出各种指标。

项目使用uv和venv管理环境。.env里有你可以自由使用的LLM API信息，是OpenAI compatible chat completions格式。

agent loop 的system prompt和tool description要细心编写，详细指导它如何工作。