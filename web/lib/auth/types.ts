// TODO(PLAN Step 7): 백엔드 OpenAPI에서 생성한 타입(pnpm gen:api)으로 교체한다.
import type { Provider } from "@/lib/config";

export type ConsentType =
  | "terms_of_service"
  | "privacy_policy"
  | "age_over_14"
  | "marketing"
  | "quality_log_collection";

export interface UserProfile {
  id: string;
  display_name: string | null;
  email: string | null;
  is_private_email: boolean;
  status: "active" | "pending_consent" | "suspended";
  ui_locale: string;
  default_target_lang: string;
  plan: "free" | "premium";
  linked_providers: Provider[];
}

export interface RequiredConsent {
  type: ConsentType;
  version: string;
  url: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  is_new_user: boolean;
  user: UserProfile;
  required_consents: RequiredConsent[];
}

export interface AuthorizeResponse {
  authorize_url: string;
  state: string;
  expires_in: number;
}
