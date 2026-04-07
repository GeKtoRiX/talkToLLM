import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("renders the label text", () => {
    render(<StatusPill label="Connected" />);
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("applies status-pill base class", () => {
    const { container } = render(<StatusPill label="Test" />);
    expect(container.firstChild).toHaveClass("status-pill");
  });

  it("defaults to the 'default' tone class", () => {
    const { container } = render(<StatusPill label="Test" />);
    expect(container.firstChild).toHaveClass("status-pill--default");
  });

  it("applies success tone class", () => {
    const { container } = render(<StatusPill label="OK" tone="success" />);
    expect(container.firstChild).toHaveClass("status-pill--success");
  });

  it("applies warning tone class", () => {
    const { container } = render(<StatusPill label="Warning" tone="warning" />);
    expect(container.firstChild).toHaveClass("status-pill--warning");
  });

  it("applies danger tone class", () => {
    const { container } = render(<StatusPill label="Error" tone="danger" />);
    expect(container.firstChild).toHaveClass("status-pill--danger");
  });

  it("renders as a span element", () => {
    render(<StatusPill label="Span test" />);
    const el = screen.getByText("Span test");
    expect(el.tagName.toLowerCase()).toBe("span");
  });
});
