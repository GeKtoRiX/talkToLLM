import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TranscriptPanel } from "./TranscriptPanel";

describe("TranscriptPanel", () => {
  it("renders the title", () => {
    render(<TranscriptPanel title="You said" body="" />);
    expect(screen.getByText("You said")).toBeInTheDocument();
  });

  it("renders the body text", () => {
    render(<TranscriptPanel title="Title" body="Some transcript text" />);
    expect(screen.getByText("Some transcript text")).toBeInTheDocument();
  });

  it("renders both title and body simultaneously", () => {
    render(<TranscriptPanel title="Assistant" body="Hello there!" />);
    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.getByText("Hello there!")).toBeInTheDocument();
  });

  it("renders empty body without throwing", () => {
    const { container } = render(<TranscriptPanel title="T" body="" />);
    const body = container.querySelector(".panel-body");
    expect(body).toBeInTheDocument();
    expect(body).toHaveTextContent("");
  });

  it("renders the panel-card article wrapper", () => {
    const { container } = render(<TranscriptPanel title="T" body="B" />);
    expect(container.querySelector("article.panel-card")).toBeInTheDocument();
  });

  it("renders title with panel-title class", () => {
    const { container } = render(<TranscriptPanel title="My Title" body="" />);
    const titleEl = container.querySelector(".panel-title");
    expect(titleEl).toHaveTextContent("My Title");
  });
});
