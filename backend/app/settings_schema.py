from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class StrictPatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ShortText = Annotated[str, StringConstraints(max_length=200)]
BodyText = Annotated[str, StringConstraints(max_length=5000)]
StepText = Annotated[str, StringConstraints(min_length=1, max_length=500)]


def _validate_https_or_relative(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    if clean.startswith("/") and not clean.startswith("//"):
        return clean
    if clean.lower().startswith("https://"):
        return clean
    raise ValueError("URL must use https or be a relative path")


class CopyPatch(StrictPatchModel):
    heroKicker: ShortText | None = None
    heroTitle: Annotated[str, StringConstraints(max_length=300)] | None = None
    heroSubtitle: Annotated[str, StringConstraints(max_length=500)] | None = None
    primaryCta: ShortText | None = None
    secondaryCta: ShortText | None = None
    notice: Annotated[str, StringConstraints(max_length=2000)] | None = None


class LinksPatch(StrictPatchModel):
    libraryUrl: str | None = None
    supportUrl: str | None = None
    announcementUrl: str | None = None

    @field_validator("libraryUrl", "supportUrl", "announcementUrl")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return None if value is None else _validate_https_or_relative(value)


class ClientPatch(StrictPatchModel):
    serverUrl: str | None = None
    androidDownloadUrl: str | None = None
    iosGuideText: Annotated[str, StringConstraints(max_length=2000)] | None = None
    desktopGuideText: Annotated[str, StringConstraints(max_length=2000)] | None = None

    @field_validator("serverUrl", "androidDownloadUrl")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return None if value is None else _validate_https_or_relative(value)


class TimelineItem(StrictPatchModel):
    date: Annotated[str, StringConstraints(max_length=100)] = ""
    body: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class AnnouncementPatch(StrictPatchModel):
    title: Annotated[str, StringConstraints(max_length=200)] | None = None
    body: BodyText | None = None
    linkUrl: str | None = None
    linkLabel: ShortText | None = None
    timeline: list[TimelineItem] | None = Field(default=None, max_length=50)

    @field_validator("linkUrl")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_https_or_relative(value)


class FeaturesPatch(StrictPatchModel):
    registration: bool | None = None
    showLibraryEntry: bool | None = None
    showSupportEntry: bool | None = None
    showAnnouncements: bool | None = None


class OperationsPatch(StrictPatchModel):
    inactivityAutoDisable: bool | None = None
    inactiveDays: int | None = Field(default=None, ge=1, le=3650)
    newUserGraceDays: int | None = Field(default=None, ge=0, le=3650)
    lastInactivityCheckAt: Annotated[str, StringConstraints(max_length=100)] | None = None
    lastInactivityDisabled: int | None = Field(default=None, ge=0, le=1_000_000)


class BenefitItem(StrictPatchModel):
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class FaqItem(StrictPatchModel):
    q: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    a: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class SectionsPatch(StrictPatchModel):
    benefits: list[BenefitItem] | None = Field(default=None, max_length=20)
    steps: list[StepText] | None = Field(default=None, max_length=30)
    faq: list[FaqItem] | None = Field(default=None, max_length=50)


class PublicSettingsPatch(StrictPatchModel):
    siteName: Annotated[str, StringConstraints(max_length=80)] | None = None
    tagline: Annotated[str, StringConstraints(max_length=160)] | None = None
    copy_: CopyPatch | None = Field(default=None, alias="copy")
    links: LinksPatch | None = None
    client: ClientPatch | None = None
    announcement: AnnouncementPatch | None = None
    features: FeaturesPatch | None = None
    operations: OperationsPatch | None = None
    sections: SectionsPatch | None = None
