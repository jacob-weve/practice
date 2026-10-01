// 백엔드 OpenAPI에서 생성한 타입(schema.d.ts)의 별칭. 직접 정의하지 않는다 (CLAUDE.md §2.2).
// 스키마가 바뀌면 `pnpm gen:api`로 다시 생성한다.
import type { components } from "./schema";

type S = components["schemas"];

export type UserProfile = S["UserProfile"];
export type AuthTokenResponse = S["AuthTokenResponse"];
export type AuthorizeResponse = S["AuthorizeResponse"];
export type RequiredConsent = S["RequiredConsent"];
export type ConsentItem = S["ConsentItem"];
export type ConsentType = ConsentItem["type"];
export type ConsentState = S["ConsentState"];
export type ConsentListResponse = S["ConsentListResponse"];
export type UserResponse = S["UserResponse"];
export type UserUpdateRequest = S["UserUpdateRequest"];

export type ToneOptionsResponse = S["ToneOptionsResponse"];
export type PersonaOut = S["PersonaOut"];
export type ToneTransformRequest = S["ToneTransformRequest"];
export type ToneTransformResponse = S["ToneTransformResponse"];
export type Persona = ToneTransformRequest["persona"];
export type Relation = NonNullable<ToneTransformRequest["relation"]>;
export type Lang = ToneTransformRequest["target_lang"];
export type Intent = S["Intent"];
export type EmotionOut = S["EmotionOut"];
export type RedFlagOut = S["RedFlagOut"];
export type VariantOut = S["VariantOut"];

export type ReplyInterpretRequest = S["ReplyInterpretRequest"];
export type ReplyInterpretResponse = S["ReplyInterpretResponse"];
export type Turn = S["Turn"];
export type Interpretation = S["Interpretation"];
export type Guide = S["Guide"];
export type SuggestedReplyOut = S["SuggestedReplyOut"];

export type FeedbackRequest = S["FeedbackRequest"];
