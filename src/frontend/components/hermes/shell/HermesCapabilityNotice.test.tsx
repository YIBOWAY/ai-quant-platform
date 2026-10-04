import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HermesCapabilityNotice } from "./HermesCapabilityNotice";

describe("Hermes read and send availability are separate", () => {
  it("keeps sending blocked while explaining a healthy read-only connection", () => {
    const html = renderToStaticMarkup(<HermesCapabilityNotice locale="zh" deliveryState="blocked_in_this_slice" readState="available"/>);
    expect(html).toContain('data-delivery-state="blocked_in_this_slice"');
    expect(html).toContain("当前为只读模式");
    expect(html).toContain("可查看已保存会话和研究记录；暂不能发送新消息");
    expect(html).not.toContain("本地连接尚未就绪");
  });
  it("does not call a pending read a broken connection", () => {
    const html = renderToStaticMarkup(<HermesCapabilityNotice locale="zh" deliveryState="blocked_in_this_slice" readState="loading"/>);
    expect(html).toContain("正在读取连接状态");
    expect(html).not.toContain("连接尚未就绪");
    expect(html).not.toContain("当前为只读模式");
  });
  it("keeps the unavailable diagnostic for an actual read failure", () => {
    const html = renderToStaticMarkup(<HermesCapabilityNotice locale="zh" deliveryState="blocked_in_this_slice" readState="unavailable"/>);
    expect(html).toContain("Hermes 对话当前不可用");
    expect(html).not.toContain("当前为只读模式");
  });
});
