"""
ESCO Skill Taxonomy Integration Service.

This service provides skill normalization, related skill lookup, and semantic
skill matching using the ESCO (European Skills, Competences, Qualifications 
and Occupations) taxonomy.

https://esco.ec.europa.eu/
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from app.core.config import settings
from app.services.skill_catalog import SKILL_CATEGORIES

logger = logging.getLogger(__name__)

# Threshold for fuzzy matching
FUZZY_THRESHOLD = 85


@dataclass
class NormalizedSkill:
    """Represents a skill normalized to ESCO taxonomy."""
    esco_uri: str
    preferred_label: str
    alt_labels: list[str] = field(default_factory=list)
    description: str | None = None
    skill_type: str = "skill"  # skill, knowledge, competence
    broader_skills: list[str] = field(default_factory=list)
    narrower_skills: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)
    category: str | None = None
    confidence: float = 1.0

    def matches(self, query: str) -> bool:
        """Check if query matches this skill (preferred or alt labels)."""
        query_lower = query.lower().strip()
        if query_lower == self.preferred_label.lower():
            return True
        return any(query_lower == alt.lower() for alt in self.alt_labels)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "esco_uri": self.esco_uri,
            "preferred_label": self.preferred_label,
            "alt_labels": self.alt_labels,
            "description": self.description,
            "skill_type": self.skill_type,
            "broader_skills": self.broader_skills,
            "narrower_skills": self.narrower_skills,
            "related_skills": self.related_skills,
            "category": self.category,
            "confidence": self.confidence,
        }


@dataclass
class RelatedSkill:
    """A skill related to another skill with relationship type and score."""
    skill: NormalizedSkill
    relationship: str  # "broader", "narrower", "related", "synonym"
    similarity_score: float

    def to_dict(self) -> dict[str, Any]:
        """
        Serializes this object into a plain dictionary.
        """
        return {
            "skill": self.skill.to_dict(),
            "relationship": self.relationship,
            "similarity_score": self.similarity_score,
        }


@dataclass
class SkillCluster:
    """A cluster of related skills from ESCO hierarchy."""
    cluster_id: str
    cluster_name: str
    skills: list[str]
    parent_cluster: str | None = None
    description: str | None = None

    def contains_skill(self, skill: str) -> bool:
        """Check if skill is in this cluster."""
        skill_lower = skill.lower().strip()
        return any(skill_lower == s.lower() for s in self.skills)


class ESCOSkillService:
    """
    Service for ESCO taxonomy operations.
    
    Provides skill normalization, related skill lookup, and semantic
    skill matching using the ESCO taxonomy.
    """
    
    def __init__(self, esco_data_path: str | Path | None = None):
        """Initialize the ESCO service with optional data path."""
        self._skills_by_uri: dict[str, NormalizedSkill] = {}
        self._skills_by_label: dict[str, NormalizedSkill] = {}
        self._skill_clusters: dict[str, SkillCluster] = {}
        self._loaded = False
        self._real_esco_loaded = False
        
        if esco_data_path:
            if not self.load_esco_data(esco_data_path):
                logger.warning("Real ESCO data unavailable; falling back to built-in skill catalog")
                self._initialize_from_catalog()
        else:
            configured_path = _resolve_data_path(settings.esco_data_path)
            if configured_path.exists() and self.load_esco_data(configured_path):
                self._real_esco_loaded = True
            else:
                logger.warning("Real ESCO data file not found; falling back to built-in skill catalog")
                self._initialize_from_catalog()
    
    def load_esco_data(self, path: str | Path) -> int:
        """
        Load ESCO taxonomy data from JSON file.
        
        Args:
            path: Path to ESCO JSON file
            
        Returns:
            Number of skills loaded
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f"ESCO data file not found: {path}")
            return 0
        
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            
            self._skills_by_uri.clear()
            self._skills_by_label.clear()
            self._skill_clusters.clear()
            count = 0
            for skill_data in data.get("skills", []):
                skill = self._parse_skill(skill_data)
                if skill:
                    self._index_skill(skill)
                    count += 1
            
            # Load skill clusters
            for cluster_data in data.get("skillGroups", []):
                cluster = self._parse_cluster(cluster_data)
                if cluster:
                    self._skill_clusters[cluster.cluster_id] = cluster
            
            self._loaded = True
            self._real_esco_loaded = count > 0
            logger.info(f"Loaded {count} ESCO skills from {path}")
            return count
            
        except Exception as e:
            logger.error(f"Failed to load ESCO data: {e}")
            return 0
    
    def _parse_skill(self, data: dict[str, Any]) -> NormalizedSkill | None:
        """Parse a skill from ESCO JSON data."""
        try:
            uri = data.get("uri", "")
            if not uri:
                return None
            
            labels = data.get("preferredLabel", {})
            if isinstance(labels, str):
                preferred = labels
            else:
                preferred = labels.get("en", "") or labels.get("ar", "")
            if not preferred:
                return None
            
            alt_labels_data = data.get("altLabels", {})
            if isinstance(alt_labels_data, list):
                alt_labels = [str(item) for item in alt_labels_data]
            elif isinstance(alt_labels_data, str):
                alt_labels = [alt_labels_data]
            else:
                alt_labels = alt_labels_data.get("en", []) + alt_labels_data.get("ar", [])
            
            return NormalizedSkill(
                esco_uri=uri,
                preferred_label=preferred,
                alt_labels=alt_labels,
                description=data.get("description"),
                skill_type=data.get("skillType", "skill"),
                broader_skills=data.get("broader", []),
                narrower_skills=data.get("narrower", []),
                related_skills=data.get("related", []),
            )
        except Exception as e:
            logger.debug(f"Failed to parse skill: {e}")
            return None
    
    def _parse_cluster(self, data: dict[str, Any]) -> SkillCluster | None:
        """Parse a skill cluster from JSON data."""
        try:
            return SkillCluster(
                cluster_id=data.get("id", ""),
                cluster_name=data.get("label", ""),
                skills=data.get("skills", []),
                parent_cluster=data.get("parent"),
                description=data.get("description"),
            )
        except Exception:
            return None
    
    def _index_skill(self, skill: NormalizedSkill) -> None:
        """Index a skill for fast lookup."""
        self._skills_by_uri[skill.esco_uri] = skill
        
        # Index by preferred label
        key = skill.preferred_label.lower().strip()
        self._skills_by_label[key] = skill
        
        # Index by all alt labels
        for alt in skill.alt_labels:
            alt_key = alt.lower().strip()
            if alt_key not in self._skills_by_label:
                self._skills_by_label[alt_key] = skill
    
    def _initialize_from_catalog(self) -> None:
        """Initialize with built-in skill catalog as ESCO fallback."""
        for category, skills in SKILL_CATEGORIES.items():
            for skill in skills:
                uri = f"local:{skill.replace(' ', '-').lower()}"
                normalized = NormalizedSkill(
                    esco_uri=uri,
                    preferred_label=skill,
                    alt_labels=[],
                    category=category,
                    confidence=0.9,
                )
                self._index_skill(normalized)
                
                # Create cluster from category
                cluster_id = category.lower().replace(" ", "-")
                if cluster_id not in self._skill_clusters:
                    self._skill_clusters[cluster_id] = SkillCluster(
                        cluster_id=cluster_id,
                        cluster_name=category,
                        skills=[],
                    )
                self._skill_clusters[cluster_id].skills.append(skill)
        
        self._loaded = True
        logger.info(f"Initialized with {len(self._skills_by_uri)} skills from built-in catalog")

    def is_real_esco_loaded(self) -> bool:
        """Returns whether the service loaded real ESCO data instead of local fallback data."""
        return self._real_esco_loaded
    
    def normalize_skill(self, skill: str) -> NormalizedSkill | None:
        """
        Normalize a skill string to its ESCO canonical form.
        
        Args:
            skill: Raw skill string from CV or job
            
        Returns:
            NormalizedSkill if found, None otherwise
        """
        if not skill:
            return None
        
        skill_lower = skill.lower().strip()
        
        # Direct lookup
        if skill_lower in self._skills_by_label:
            return self._skills_by_label[skill_lower]
        
        # Fuzzy match for typos/variations
        best_match: NormalizedSkill | None = None
        best_score = 0
        
        for label, normalized in self._skills_by_label.items():
            # Skip if labels are too different in length
            if abs(len(label) - len(skill_lower)) > max(5, len(skill_lower) * 0.5):
                continue
            
            score = fuzz.ratio(skill_lower, label)
            if score > best_score and score >= FUZZY_THRESHOLD:
                best_score = score
                best_match = normalized
        
        if best_match:
            # Return with adjusted confidence
            return NormalizedSkill(
                esco_uri=best_match.esco_uri,
                preferred_label=best_match.preferred_label,
                alt_labels=best_match.alt_labels,
                description=best_match.description,
                skill_type=best_match.skill_type,
                broader_skills=best_match.broader_skills,
                narrower_skills=best_match.narrower_skills,
                related_skills=best_match.related_skills,
                category=best_match.category,
                confidence=best_score / 100.0,  # Fuzzy match confidence
            )
        
        return None
    
    def get_related_skills(
        self, 
        skill: str, 
        depth: int = 1,
        include_synonyms: bool = True,
    ) -> list[RelatedSkill]:
        """
        Get skills related to the given skill from ESCO hierarchy.
        
        Args:
            skill: Skill to find relations for
            depth: How deep to traverse the hierarchy (1 = direct relations)
            include_synonyms: Whether to include synonym matches
            
        Returns:
            List of related skills with relationship types and scores
        """
        normalized = self.normalize_skill(skill)
        if not normalized:
            return []
        
        related: list[RelatedSkill] = []
        seen_uris: set[str] = {normalized.esco_uri}
        
        # Add synonyms (skills with same normalized form)
        if include_synonyms:
            for label, ns in self._skills_by_label.items():
                if ns.esco_uri == normalized.esco_uri and label.lower() != normalized.preferred_label.lower():
                    related.append(RelatedSkill(
                        skill=ns,
                        relationship="synonym",
                        similarity_score=0.95,
                    ))
        
        # Add broader skills (parent concepts)
        for broader_uri in normalized.broader_skills[:depth]:
            if broader_uri in self._skills_by_uri and broader_uri not in seen_uris:
                seen_uris.add(broader_uri)
                broader = self._skills_by_uri[broader_uri]
                related.append(RelatedSkill(
                    skill=broader,
                    relationship="broader",
                    similarity_score=0.7,
                ))
        
        # Add narrower skills (child concepts)
        for narrower_uri in normalized.narrower_skills[:depth * 2]:
            if narrower_uri in self._skills_by_uri and narrower_uri not in seen_uris:
                seen_uris.add(narrower_uri)
                narrower = self._skills_by_uri[narrower_uri]
                related.append(RelatedSkill(
                    skill=narrower,
                    relationship="narrower",
                    similarity_score=0.75,
                ))
        
        # Add explicitly related skills
        for related_uri in normalized.related_skills[:depth * 2]:
            if related_uri in self._skills_by_uri and related_uri not in seen_uris:
                seen_uris.add(related_uri)
                rel_skill = self._skills_by_uri[related_uri]
                related.append(RelatedSkill(
                    skill=rel_skill,
                    relationship="related",
                    similarity_score=0.6,
                ))
        
        return related
    
    def get_skill_cluster(self, skill: str) -> SkillCluster | None:
        """Get the skill cluster this skill belongs to."""
        normalized = self.normalize_skill(skill)
        if not normalized:
            return None
        
        # Check category first
        if normalized.category:
            cluster_id = normalized.category.lower().replace(" ", "-")
            if cluster_id in self._skill_clusters:
                return self._skill_clusters[cluster_id]
        
        # Search in clusters
        skill_lower = skill.lower().strip()
        for cluster in self._skill_clusters.values():
            if cluster.contains_skill(skill_lower):
                return cluster
        
        return None
    
    def skills_in_same_cluster(self, skill1: str, skill2: str) -> bool:
        """Check if two skills belong to the same cluster."""
        cluster1 = self.get_skill_cluster(skill1)
        cluster2 = self.get_skill_cluster(skill2)
        
        if not cluster1 or not cluster2:
            return False
        
        return cluster1.cluster_id == cluster2.cluster_id
    
    def search_skills(
        self, 
        query: str, 
        limit: int = 10,
        category: str | None = None,
    ) -> list[tuple[NormalizedSkill, float]]:
        """
        Search ESCO taxonomy by label or description.
        
        Args:
            query: Search query
            limit: Maximum results to return
            category: Optional category filter
            
        Returns:
            List of (skill, score) tuples
        """
        if not query:
            return []
        
        query_lower = query.lower().strip()
        results: list[tuple[NormalizedSkill, float]] = []
        
        for label, skill in self._skills_by_label.items():
            # Category filter
            if category and skill.category and skill.category.lower() != category.lower():
                continue
            
            # Direct match
            if query_lower == label:
                results.append((skill, 1.0))
                continue
            
            # Partial match
            if query_lower in label:
                score = len(query_lower) / len(label)
                results.append((skill, score))
                continue
            
            # Fuzzy match
            score = fuzz.partial_ratio(query_lower, label) / 100.0
            if score >= 0.7:
                results.append((skill, score * 0.8))  # Reduce fuzzy match score
        
        # Sort by score and return top results
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]
    
    def compute_skill_similarity(self, skill1: str, skill2: str) -> float:
        """
        Compute semantic similarity between two skills.
        
        Returns:
            Similarity score between 0.0 and 1.0
        """
        if not skill1 or not skill2:
            return 0.0
        
        s1_lower = skill1.lower().strip()
        s2_lower = skill2.lower().strip()
        
        # Exact match
        if s1_lower == s2_lower:
            return 1.0
        
        # Normalize both
        norm1 = self.normalize_skill(skill1)
        norm2 = self.normalize_skill(skill2)
        
        # Both unknown - use string similarity
        if not norm1 and not norm2:
            return fuzz.ratio(s1_lower, s2_lower) / 100.0
        
        # One known, one unknown
        if not norm1 or not norm2:
            known = norm1 or norm2
            unknown = s1_lower if not norm1 else s2_lower
            
            # Check if unknown matches any alt label
            if known.matches(unknown):
                return 0.95
            
            return fuzz.ratio(unknown, known.preferred_label) / 100.0 * 0.5
        
        # Both known - check ESCO relationships
        if norm1.esco_uri == norm2.esco_uri:
            return 1.0
        
        # Check if related
        related = self.get_related_skills(skill1, depth=2)
        for rel in related:
            if rel.skill.esco_uri == norm2.esco_uri:
                return rel.similarity_score
        
        # Check same cluster
        if self.skills_in_same_cluster(skill1, skill2):
            return 0.5
        
        return fuzz.ratio(norm1.preferred_label, norm2.preferred_label) / 100.0 * 0.3
    
    @property
    def is_loaded(self) -> bool:
        """Check if ESCO data is loaded."""
        return self._loaded
    
    @property
    def skill_count(self) -> int:
        """Get total number of unique skills."""
        return len(self._skills_by_uri)
    
    @property
    def cluster_count(self) -> int:
        """Get total number of skill clusters."""
        return len(self._skill_clusters)


# Singleton instance
_esco_service: ESCOSkillService | None = None


def get_esco_service() -> ESCOSkillService:
    """Get or create the ESCO service singleton."""
    global _esco_service
    if _esco_service is None:
        _esco_service = ESCOSkillService()
    return _esco_service


def reset_esco_service() -> None:
    """Reset the ESCO service singleton (for testing)."""
    global _esco_service
    _esco_service = None


def _resolve_data_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute() or path.exists():
        return path
    return Path(__file__).resolve().parents[3] / path
