import { apiPost } from "./apiClient";
import {
  buildBriefGenerateRequest,
  type BriefArchivePayload,
  type BriefIssueEnvelope,
  type BriefSourceWatermark,
} from "./briefArchive";

export function createBriefArchive(
  payload: BriefArchivePayload,
  sourceWatermark: BriefSourceWatermark,
) {
  return apiPost<BriefIssueEnvelope>(
    "/api/brief/issues/generate",
    buildBriefGenerateRequest(payload, sourceWatermark),
  );
}
