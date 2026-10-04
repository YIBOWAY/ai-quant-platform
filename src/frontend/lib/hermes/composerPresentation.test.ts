import { describe, expect, it } from "vitest";

import { CHAT_PROMPT_MAX_BYTES } from "./darkIdentity";
import {
  composerDraftState,
  composerErrorMessage,
  formatComposerLifecycleStatus,
  formatComposerReceiptStatus,
} from "./composerPresentation";
import { WorkspaceClientError } from "./workspaceClient";

describe("composerPresentation", () => {
  it("validates the draft by UTF-8 bytes rather than JavaScript characters", () => {
    expect(composerDraftState("量化", "zh").byteLength).toBe(6);
    expect(
      composerDraftState("a".repeat(CHAT_PROMPT_MAX_BYTES), "zh").valid,
    ).toBe(true);

    const oversized = composerDraftState(
      "a".repeat(CHAT_PROMPT_MAX_BYTES + 1),
      "zh",
    );
    expect(oversized.valid).toBe(false);
    expect(oversized.overLimitBytes).toBe(1);
    expect(oversized.counterText).toContain("超出 1 字节");

    expect(composerDraftState("   ", "zh").valid).toBe(false);
  });

  it("renders Chinese and English byte counters without rounding KiB", () => {
    expect(composerDraftState("量化", "zh").counterText).toBe(
      "已输入 6 / 16,384 字节",
    );
    expect(composerDraftState("quant", "en").counterText).toBe(
      "5 / 16,384 bytes",
    );
  });

  it("localizes receipt and lifecycle states without exposing command or run ids", () => {
    expect(
      formatComposerReceiptStatus("accepted", "123456789abcdef", "internal reason", "zh"),
    ).toBe("已接受");
    expect(
      formatComposerLifecycleStatus(
        "succeeded",
        "123456789abcdef",
        "run_123456789012345",
        "zh",
      ),
    ).toBe("已成功");
    expect(
      formatComposerLifecycleStatus("queued", "123456789abcdef", null, "en"),
    ).toBe("Queued");
  });

  it("maps prompt and Keychain failures to actionable locale copy", () => {
    expect(
      composerErrorMessage(
        new WorkspaceClientError("raw backend text", 400, "prompt_too_large"),
        "zh",
      ),
    ).toContain("16,384 字节");
    expect(
      composerErrorMessage(
        new WorkspaceClientError(
          "intent crypto authority is temporarily unavailable",
          503,
          "intent_crypto_unavailable",
        ),
        "zh",
      ),
    ).toContain("macOS 钥匙串");
    expect(
      composerErrorMessage(
        new WorkspaceClientError("intent crypto unavailable", 503, "intent_crypto_unavailable"),
        "en",
      ),
    ).toContain("macOS Keychain");
  });

  it("maps a corrupt stored intent to a safe next action", () => {
    const message = composerErrorMessage(
      new WorkspaceClientError(
        "stored payload intent kind is invalid",
        409,
        "intent_payload_corrupt",
      ),
      "zh",
    );
    expect(message).toBe(
      "本地消息存储读取失败，这条消息尚未发送。请先重启本地服务；如果仍失败，请检查 HQA 日志。不要重试同一次发送。",
    );
    expect(message).not.toContain("intent_payload_corrupt");
    expect(message).not.toContain("stored payload");
  });

  it("distinguishes a safe GET retry from an unknown POST outcome", () => {
    expect(
      composerErrorMessage(
        new WorkspaceClientError(
          "raw GET timeout",
          504,
          "workspace_request_timeout",
        ),
        "zh",
      ),
    ).toContain("检查服务状态后重试");
    const post = composerErrorMessage(
      new WorkspaceClientError("raw POST timeout", 504, "outcome_unknown"),
      "zh",
    );
    expect(post).toContain("重试同一次发送");
    expect(post).not.toContain("raw POST timeout");
  });
});
