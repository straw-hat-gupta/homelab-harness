import { screen, within } from "@testing-library/react";

import { templates } from "@/registry";
import { axeViolations, renderWithApp } from "@/test/render";
import { shapeFixtures, templateOptions } from "@/test/fixtures";
import { Widget } from "@/widgets/widget";

describe("every template renders every shape it accepts (contract)", () => {
  const cases = templates.flatMap((t) => t.accepts.map((shape) => [t.name, shape] as const));

  it.each(cases)("%s renders %s fixtures accessibly", async (name, shape) => {
    const { container } = await renderWithApp(
      <Widget
        config={{ template: name, options: templateOptions[name] }}
        data={shapeFixtures[shape]}
      />,
    );
    expect(container).not.toBeEmptyDOMElement();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("has fixture options for every template", () => {
    for (const t of templates)
      expect(t.options.safeParse(templateOptions[t.name]).success).toBe(true);
  });
});

describe("stat", () => {
  it("formats bytes against the maximum and shows a meter", async () => {
    await renderWithApp(
      <Widget
        config={{ template: "stat", options: { label: "Memory" } }}
        data={shapeFixtures.scalar}
      />,
    );
    expect(screen.getByText("1.0 GiB")).toBeInTheDocument();
    expect(screen.getByText("of 4.0 GiB")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Memory" })).toHaveAttribute("aria-valuenow", "25");
  });

  it("shows an unknown value as a dash, without a meter", async () => {
    await renderWithApp(
      <Widget
        config={{ template: "stat", options: { label: "Uptime" } }}
        data={{ shape: "scalar", data: { value: null, unit: "seconds" } }}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByRole("meter")).toBeNull();
  });
});

describe("table", () => {
  it("renders the chosen columns and an empty state", async () => {
    await renderWithApp(
      <Widget
        config={{ template: "table", options: templateOptions.table }}
        data={shapeFixtures.rows}
      />,
    );
    const table = screen.getByRole("table", { name: "Nodes" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Name", "Status"]);
    expect(within(table).getByText("pve2")).toBeInTheDocument();
  });

  it("shows target text as text, never markup", async () => {
    await renderWithApp(
      <Widget
        config={{ template: "table", options: templateOptions.table }}
        data={{ shape: "rows", data: { rows: [{ name: "<img src=x onerror=alert(1)>" }] } }}
      />,
    );
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("status-list", () => {
  it("links rows to object pages when told which fields to use", async () => {
    await renderWithApp(
      <Widget
        config={{
          template: "status-list",
          options: {
            ...(templateOptions["status-list"] as object),
            link: { typeField: "type", idField: "id" },
          },
        }}
        data={shapeFixtures.rows}
      />,
    );
    const list = screen.getByRole("list", { name: "Nodes" });
    expect(within(list).getByRole("link", { name: /pve1/ })).toHaveAttribute(
      "href",
      "/objects/node/home%3Apve1",
    );
    expect(within(list).getByText("offline")).toBeInTheDocument();
  });
});

describe("log-tail", () => {
  it("keeps only the newest lines", async () => {
    await renderWithApp(
      <Widget
        config={{ template: "log-tail", options: { label: "Log", maxLines: 1 } }}
        data={shapeFixtures["log-lines"]}
      />,
    );
    const log = screen.getByRole("log", { name: "Log" });
    expect(log).toHaveTextContent("finished");
    expect(log).not.toHaveTextContent("starting vzdump");
  });
});

describe("markdown", () => {
  it("renders Markdown but no raw HTML or script links", async () => {
    await renderWithApp(
      <Widget
        config={{ template: "markdown" }}
        data={{
          shape: "markdown",
          data: { markdown: "# pve1\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))" },
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "pve1" })).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("x").getAttribute("href") ?? "").not.toContain("javascript");
  });
});
