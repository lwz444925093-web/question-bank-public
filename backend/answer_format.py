"""Shared public answer format for all solution-generation paths."""
ANSWER_FORMAT_INSTRUCTION = """答案answer（或ai_answer）是学生在试卷答题区应写出的完整、可独立阅卷的规范作答，不是结论摘要。选择题按要求给选项；填空题按空给结果；解答题逐小问写必要列式、推导、单位和结论。证明题必须在答案栏写出从已知条件到结论的完整证明步骤与依据，不能仅重述待证结论、写“成立”“略”或“证明见解析”。判断并证明、求条件并证明的题，答案同时包含判断/条件及其证明。只有题目明确要求直接写出结果的小问可省略过程。各步骤分paragraph/equation块，公式使用math/LaTeX。
解析explanation（或ai_explanation）补充解题思路、条件运用、方法和易错点，可以解释答案中的步骤，但不能成为答案缺失必要步骤的替代。输出公开的规范解答，不输出内部思维链，不虚构条件。自检须单独检查答案栏能否直接作为试卷作答：即使解析中有证明，答案栏只有结论也不算完整，应在本次回复中补全；若仍缺必要步骤，solution_check不得为ready。"""
