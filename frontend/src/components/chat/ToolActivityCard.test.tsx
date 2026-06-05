import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ToolActivityCard } from "./ToolActivityCard";

describe("ToolActivityCard", () => {
  it("shows the tool status and prioritizes useful search arguments", () => {
    render(
      <ToolActivityCard
        toolCall={{
          tool: "mteam_search",
          status: "success",
          arguments: {
            imdb: "tt1160419",
            sort_by: "most_seeded",
            mode: "movie",
            keyword: "Dune"
          }
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "mteam_search" })).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();

    const items = screen.getAllByRole("term").map((term) => term.closest(".tool-activity-item"));
    expect(items.map((item) => within(item as HTMLElement).getByRole("term").textContent)).toEqual([
      "keyword",
      "mode",
      "sort_by",
      "imdb"
    ]);
    expect(screen.getByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("movie")).toBeInTheDocument();
    expect(screen.getByText("most_seeded")).toBeInTheDocument();
  });

  it("renders an empty argument state", () => {
    render(<ToolActivityCard toolCall={{ tool: "member_profile", status: "success", arguments: {} }} />);

    expect(screen.getByText("无参数")).toBeInTheDocument();
  });
});
