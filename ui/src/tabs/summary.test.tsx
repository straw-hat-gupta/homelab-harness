import { screen, within } from "@testing-library/react";

import { ApiError } from "@/api/client";
import { QueryError } from "@/components/query-state";
import { tabsFor } from "@/registry";
import { SummaryView } from "@/tabs/summary.tab";
import { datacenterSummary, guestSummary, nodeSummary } from "@/test/fixtures";
import { axeViolations, renderWithApp } from "@/test/render";

describe("Summary tab", () => {
  it("composes stat widgets and a properties table for a node", async () => {
    const { container } = await renderWithApp(<SummaryView summary={nodeSummary} />);
    expect(screen.getByText("8.0 %")).toBeInTheDocument();
    expect(screen.getByText("16.0 GiB")).toBeInTheDocument();
    expect(screen.getByText("14d")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Properties" });
    expect(within(table).getByText("AMD Ryzen 9 7950X")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("lists a datacenter's nodes as links", async () => {
    await renderWithApp(<SummaryView summary={datacenterSummary} />);
    const members = screen.getByRole("list", { name: "Members" });
    expect(within(members).getByRole("link", { name: /pve2/ })).toHaveAttribute(
      "href",
      "/objects/node/home%3Apve2",
    );
  });

  it("marks target-sourced values as untrusted", async () => {
    await renderWithApp(<SummaryView summary={guestSummary} />);
    const row = screen.getByText("config: cipassword").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("target (untrusted)")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("[MASKED]")).toBeInTheDocument();
  });

  it("is the first tab of every core object type, then Tasks", () => {
    for (const type of ["datacenter", "node", "qemu", "lxc", "storage"]) {
      expect(tabsFor(type).map((t) => t.id)).toEqual(["summary", "tasks"]);
    }
  });
});

describe("query errors", () => {
  it("asks for an owner token on a 401", async () => {
    await renderWithApp(<QueryError error={new ApiError(401, "an owner token is required")} />);
    expect(screen.getByLabelText("Owner token")).toHaveAttribute("type", "password");
  });

  it("shows the server's safe message otherwise", async () => {
    await renderWithApp(<QueryError error={new ApiError(502, "the cluster did not answer")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("the cluster did not answer");
  });
});
