from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

LEBANESE_ARABIC_SYSTEM_PROMPT = """You are an expert technical recruiter and interviewer. You speak FLUENT LEBANESE ARABIC (لهجة لبنانية) and English.

IMPORTANT RULES FOR COMMUNICATION:
1. The candidate can answer in ENGLISH or LEBANESE ARABIC (لهجة لبنانية مش عامية لبنانية مش فصحى)
2. You MUST understand both languages perfectly
3. You MUST respond in the SAME LANGUAGE as the candidate's answer
4. For Lebanese Arabic, use natural spoken Lebanese dialect (كلام زي ما بنحكي بالبنان)

LEBANESE ARABIC PHRASES YOU SHOULD USE:
- Instead of "كيف حالك؟" (Fusha), use "كيفك؟" or "شو أخبارك؟"
- Instead of "من فضلك", use "لو سمحت" or "من فضلك" (both are ok)
- Instead of "شكراً لك", use "شكراً" or "مرسي"
- Use "بصي" or "بس" for "but"
- Use "هيك" for "like this"
- Use "هون" for "here"
- Use "هونيك" for "there"
- Use "كتير" for "very/a lot"
- Use "شو" for "what"
- Use "ليش" for "why"
- Use "كيف" for "how"
- Use "مِن" for "when"
- Use "وين" for "where"
- Use "مَن" for "who"
- Use "كام" for "how much/how many"

When evaluating answers:
- Be fair and objective
- Consider both technical accuracy and communication clarity
- If the answer is partially correct, give partial credit
- Provide constructive feedback in the same language

YOUR TASK: Conduct technical interviews, evaluate answers, and provide helpful feedback.
"""

ANSWER_EVALUATION_PROMPT = """You are evaluating a candidate's answer in a technical interview.

Question: {question}
Skill being tested: {skill}
Candidate's Answer: {answer}
Difficulty level: {difficulty}

Please evaluate the answer and return a JSON with:
{{
    "score": float between 0.0 and 1.0,
    "feedback": "constructive feedback in the same language as the answer",
    "strengths": ["list of strengths"],
    "weaknesses": ["list of weaknesses or areas for improvement"],
    "language_detected": "arabic" or "english",
    "technical_accuracy": float between 0.0 and 1.0,
    "completeness": float between 0.0 and 1.0,
    "clarity": float between 0.0 and 1.0
}}

IMPORTANT:
- The feedback MUST be in the SAME LANGUAGE as the candidate's answer
- If the answer is in Arabic (especially Lebanese), respond in Lebanese Arabic
- If the answer is in English, respond in English
- Be fair and objective
"""

FOLLOWUP_QUESTION_PROMPT = """You are a technical interviewer. The candidate just answered a question.

Original Question: {question}
Candidate's Answer: {answer}
Skill: {skill}
Previous Score: {score}

Generate a relevant follow-up question to:
1. Clarify the answer if unclear
2. Test deeper understanding
3. Explore related topics

Return a JSON with:
{{
    "followup_question": "the follow-up question in ENGLISH (questions are always in English)",
    "reason": "why this follow-up is needed",
    "expected_topic": "what topic/concept this tests"
}}

IMPORTANT: The follow-up question MUST be in English. Only the evaluation/feedback can be in Arabic.
"""

NEGATION_DETECTION_PROMPT = """Analyze this CV text and identify skills with their context.

CV Text: {cv_text}

Return a JSON with:
{{
    "skills_with_context": [
        {{
            "skill": "skill name",
            "context": "the sentence/phrase mentioning this skill",
            "status": "has_experience" OR "learning" OR "no_experience" OR "unknown",
            "years": number or null,
            "level": "junior" OR "mid" OR "senior" OR "expert" OR "unknown",
            "confidence": 0.0 to 1.0
        }}
    ],
    "negative_skills": ["skills the person explicitly says they don't know"],
    "learning_skills": ["skills the person says they are learning"],
    "summary": "brief summary of the candidate's profile"
}}

Guidelines for status:
- "has_experience": "I have 5 years in Python", "Experienced with React"
- "learning": "Currently learning React", "Studying Machine Learning"
- "no_experience": "I don't know Python", "No experience with Docker"
- "unknown": when context is unclear

Extract years and level when mentioned:
- "5 years" → senior (if >=5) or mid (if 2-5) or junior (if <2)
- "expert", "senior developer" → senior/expert
- "junior", "entry level" → junior
"""


class BilingualLLMService:
    def __init__(self) -> None:
        self.llm_provider = settings.llm_provider.lower()
        self.model_name = settings.ollama_interview_model
        self.base_url = settings.ollama_base_url

    async def _chat(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        if self.llm_provider == "rule":
            logger.warning("LLM provider set to 'rule', returning default response")
            return self._default_response(messages)

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, self._chat_sync, messages, model)
        except Exception as e:
            logger.error(f"Ollama chat error: {e}")
            return self._default_response(messages)

    def _chat_sync(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        from ollama import Client as OllamaClient
        client = OllamaClient(host=self.base_url, timeout=180)
        response = client.chat(
            model=model or self.model_name,
            messages=messages,
        )
        return response["message"]["content"]

    async def _generate(self, prompt: str, model: str | None = None) -> str:
        if self.llm_provider == "rule":
            return self._default_generate_response(prompt)

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, self._generate_sync, prompt, model)
        except Exception as e:
            logger.error(f"Ollama generate error: {e}")
            return self._default_generate_response(prompt)

    def _generate_sync(self, prompt: str, model: str | None = None) -> str:
        from ollama import Client as OllamaClient
        client = OllamaClient(host=self.base_url, timeout=180)
        response = client.generate(
            model=model or self.model_name,
            prompt=prompt,
        )
        return response["response"]

    def _default_response(self, messages: list[dict[str, str]]) -> str:
        return json.dumps({
            "score": 0.5,
            "feedback": "LLM not available. Using default evaluation.",
            "strengths": ["Answer provided"],
            "weaknesses": ["Could not evaluate deeply"],
            "language_detected": "english",
            "technical_accuracy": 0.5,
            "completeness": 0.5,
            "clarity": 0.5
        })

    def _default_generate_response(self, prompt: str) -> str:
        return json.dumps({
            "skills_with_context": [],
            "negative_skills": [],
            "learning_skills": [],
            "summary": "Could not analyze with LLM"
        })

    async def evaluate_answer(
        self,
        question: str,
        answer: str,
        skill: str,
        difficulty: str = "mid"
    ) -> dict[str, Any]:
        prompt = ANSWER_EVALUATION_PROMPT.format(
            question=question,
            answer=answer,
            skill=skill,
            difficulty=difficulty
        )

        messages = [
            {"role": "system", "content": LEBANESE_ARABIC_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        response = await self._chat(messages)

        try:
            json_str = _extract_json_from_markdown(response)
            if json_str:
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        return {
            "score": 0.5,
            "feedback": "Could not evaluate the answer properly.",
            "strengths": ["Answer was provided"],
            "weaknesses": ["Evaluation incomplete"],
            "language_detected": "english",
            "technical_accuracy": 0.5,
            "completeness": 0.5,
            "clarity": 0.5
        }

    async def generate_followup_question(
        self,
        question: str,
        answer: str,
        skill: str,
        score: float
    ) -> dict[str, Any]:
        prompt = FOLLOWUP_QUESTION_PROMPT.format(
            question=question,
            answer=answer,
            skill=skill,
            score=score
        )

        messages = [
            {"role": "system", "content": LEBANESE_ARABIC_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        response = await self._chat(messages)

        try:
            json_str = _extract_json_from_markdown(response)
            if json_str:
                return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Could not parse follow-up response as JSON")

        return {
            "followup_question": f"Can you tell me more about your experience with {skill}?",
            "reason": "To explore deeper understanding",
            "expected_topic": skill
        }

    async def analyze_cv_skills(self, cv_text: str) -> dict[str, Any]:
        prompt = NEGATION_DETECTION_PROMPT.format(cv_text=cv_text[:8000])

        messages = [
            {"role": "system", "content": "You are an expert at analyzing CVs and extracting skills with context. Return valid JSON only."},
            {"role": "user", "content": prompt}
        ]

        response = await self._chat(messages, model=settings.ollama_parsing_model)

        try:
            json_str = _extract_json_from_markdown(response)
            if json_str:
                return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Could not parse CV analysis response as JSON")

        return {
            "skills_with_context": [],
            "negative_skills": [],
            "learning_skills": [],
            "summary": "Could not analyze the CV with LLM"
        }


def _extract_json_from_markdown(response: str) -> str | None:
    stripped = response.strip()
    if stripped.startswith("```"):
        pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
        match = re.search(pattern, stripped, re.DOTALL)
        if match:
            return match.group(1).strip()
    json_start = stripped.find("{")
    json_end = stripped.rfind("}")
    if json_start >= 0 and json_end > json_start:
        return stripped[json_start: json_end + 1]
    return None


def get_bilingual_llm_service() -> BilingualLLMService:
    return BilingualLLMService()
