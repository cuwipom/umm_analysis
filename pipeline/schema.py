"""
Pydantic models and enums for the Hairfall Insights ETL pipeline.

All pipeline stages import from this module. Enums define the closed
vocabularies that the LLM must output; Pydantic models enforce structural
validation at every boundary.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums — Closed vocabularies from Architecture.md
# ---------------------------------------------------------------------------

class IntentLabel(str, Enum):
    """What the user is doing in the tweet."""
    discovery = "discovery"
    complaining = "complaining"
    seeking_recommendation = "seeking_recommendation"
    sharing_success = "sharing_success"
    sharing_failure = "sharing_failure"
    asking_question = "asking_question"
    venting = "venting"
    other = "other"


class CauseCategory(str, Enum):
    """Root cause of hair fall mentioned in the tweet."""
    stress = "stress"
    water_quality = "water_quality"
    product_ingredient = "product_ingredient"
    hormonal = "hormonal"
    nutrition_deficiency = "nutrition_deficiency"
    genetics = "genetics"
    scalp_condition = "scalp_condition"
    overprocessing = "overprocessing"
    medication = "medication"
    seasonal = "seasonal"
    age = "age"
    lifestyle = "lifestyle"
    other = "other"


class BarrierCode(str, Enum):
    """Barrier preventing the user from treating hair fall."""
    price = "price"
    side_effects = "side_effects"
    ineffective = "ineffective"
    lack_of_knowledge = "lack_of_knowledge"
    no_trust = "no_trust"
    other = "other"


class Sentiment(str, Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"


class ProductType(str, Enum):
    shampoo = "shampoo"
    conditioner = "conditioner"
    treatment_mask = "treatment_mask"
    hair_oil = "hair_oil"
    hair_serum = "hair_serum"
    hair_tonic = "hair_tonic"
    supplement = "supplement"
    medication = "medication"
    natural_remedy = "natural_remedy"
    professional_treatment = "professional_treatment"
    other = "other"


class AspectCategory(str, Enum):
    """Grouped aspect categories for product evaluation."""
    sensory = "sensory"
    usability = "usability"
    hair_quality = "hair_quality"
    scalp_health = "scalp_health"
    effectiveness = "effectiveness"
    price_value = "price_value"
    availability = "availability"
    other = "other"


# ---------------------------------------------------------------------------
# LLM Response Models
# ---------------------------------------------------------------------------

class AspectExtraction(BaseModel):
    """A single aspect mentioned in the tweet."""
    aspect: AspectCategory
    sentiment: Sentiment
    span_text: str = Field(..., min_length=1, description="Exact text span from tweet")


class BrandMention(BaseModel):
    """A brand mentioned in the tweet, as extracted by the LLM."""
    brand_raw: str = Field(..., min_length=1, description="Brand name as written in tweet")
    product_type: Optional[ProductType] = None


class CauseExtraction(BaseModel):
    """A cause extracted by the LLM."""
    cause_category: CauseCategory
    matched_sentence: str = Field(default="", description="Snippet where cause was found")


class BarrierExtraction(BaseModel):
    """A barrier extracted by the LLM."""
    barrier_code: BarrierCode


class LLMResponse(BaseModel):
    """
    The structured JSON response expected from the LLM.

    This is the Pydantic gate: if the LLM response doesn't parse into this
    model, the tweet goes to the dead-letter log.
    """
    intent: IntentLabel
    causes: list[CauseExtraction] = Field(default_factory=list)
    sentiment: Sentiment
    products: list[ProductType] = Field(default_factory=list)
    barriers: list[BarrierExtraction] = Field(default_factory=list)
    aspects: list[AspectExtraction] = Field(default_factory=list)
    brands_raw: list[BrandMention] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline Data Models
# ---------------------------------------------------------------------------

class CleanedTweet(BaseModel):
    """Stage 1 output: a cleaned, normalized tweet row."""
    tweet_id: str
    full_text: str
    screen_name: str = ""
    followers_count: int = 0
    created_at: str = ""
    lang: str = ""
    source: str = ""
    retweet_count: int = 0
    like_count: int = 0
    reply_count: int = 0
    view_count: int = 0
    user_location: str = ""
    is_spam: bool = False

    @field_validator("tweet_id")
    @classmethod
    def tweet_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("tweet_id cannot be empty")
        return v.strip()

    @field_validator("full_text")
    @classmethod
    def full_text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("full_text cannot be empty")
        return v.strip()


class EnrichedTweet(BaseModel):
    """
    Stages 2-5 output: a tweet with LLM enrichment, embeddings, and
    normalized brands. This is the final shape before DB write.
    """
    # From CleanedTweet (Stage 1)
    tweet_id: str
    full_text: str
    screen_name: str = ""
    followers_count: int = 0
    created_at: str = ""
    lang: str = ""
    source: str = ""
    retweet_count: int = 0
    like_count: int = 0
    reply_count: int = 0
    view_count: int = 0
    user_location: str = ""
    is_spam: bool = False

    # From LLM enrichment (Stage 2)
    intent_label: IntentLabel = IntentLabel.other
    sentiment: Sentiment = Sentiment.neutral
    causes: list[CauseExtraction] = Field(default_factory=list)
    products: list[ProductType] = Field(default_factory=list)
    barriers: list[BarrierExtraction] = Field(default_factory=list)
    aspects: list[AspectExtraction] = Field(default_factory=list)
    brands_raw: list[BrandMention] = Field(default_factory=list)
    coded_by: str = ""  # Model name used for enrichment

    # From embedding generation (Stage 4)
    embedding: Optional[list[float]] = None

    # From brand normalization (Stage 5)
    brands_canonical: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of brand_raw → brand_canonical"
    )

    @classmethod
    def from_cleaned_and_llm(
        cls,
        cleaned: CleanedTweet,
        llm_response: LLMResponse,
        model_name: str = "",
    ) -> "EnrichedTweet":
        """Merge a CleanedTweet with its LLM response."""
        return cls(
            # Stage 1 fields
            tweet_id=cleaned.tweet_id,
            full_text=cleaned.full_text,
            screen_name=cleaned.screen_name,
            followers_count=cleaned.followers_count,
            created_at=cleaned.created_at,
            lang=cleaned.lang,
            source=cleaned.source,
            retweet_count=cleaned.retweet_count,
            like_count=cleaned.like_count,
            reply_count=cleaned.reply_count,
            view_count=cleaned.view_count,
            user_location=cleaned.user_location,
            is_spam=cleaned.is_spam,
            # Stage 2 fields
            intent_label=llm_response.intent,
            sentiment=llm_response.sentiment,
            causes=llm_response.causes,
            products=llm_response.products,
            barriers=llm_response.barriers,
            aspects=llm_response.aspects,
            brands_raw=llm_response.brands_raw,
            coded_by=model_name,
        )
