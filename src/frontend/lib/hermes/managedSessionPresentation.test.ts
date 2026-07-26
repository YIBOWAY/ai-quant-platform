import { describe, expect, it } from "vitest";

import { WorkspaceClientError } from "./workspaceClient";
import { freshManagedSessionErrorCopy } from "./managedSessionPresentation";

describe("freshManagedSessionErrorCopy", () => {
  it("localizes retryable recovery and promises exact-attempt replay", () => {
    const error = new WorkspaceClientError(
      "raw backend detail",
      503,
      "managed_session_provision_timeout",
    );

    expect(freshManagedSessionErrorCopy(error, "zh")).toContain(
      "重试同一次创建",
    );
    expect(freshManagedSessionErrorCopy(error, "zh")).not.toContain(
      "raw backend detail",
    );
    expect(freshManagedSessionErrorCopy(error, "en")).toContain(
      "same create attempt",
    );
  });

  it("keeps unknown backend errors localized and recoverable", () => {
    const error = new Error("secret internal exception");

    expect(freshManagedSessionErrorCopy(error, "zh")).toContain(
      "新会话创建失败",
    );
    expect(freshManagedSessionErrorCopy(error, "zh")).not.toContain(
      "secret internal exception",
    );
    expect(freshManagedSessionErrorCopy(error, "en")).toContain(
      "without creating a duplicate",
    );
  });
});
