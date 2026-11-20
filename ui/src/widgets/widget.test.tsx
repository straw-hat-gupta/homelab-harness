import { screen } from "@testing-library/react";

import { renderWithApp } from "@/test/render";
import { shapeFixtures } from "@/test/fixtures";
import { Widget } from "@/widgets/widget";

describe("Widget checks its config before rendering", () => {
  it("reports an unknown template", async () => {
    await renderWithApp(<Widget config={{ template: "gauge" }} data={shapeFixtures.scalar} />);
    expect(screen.getByRole("alert")).toHaveTextContent('Unknown widget template "gauge"');
  });

  it("reports a shape the template does not accept", async () => {
    await renderWithApp(
      <Widget config={{ template: "stat", options: { label: "x" } }} data={shapeFixtures.rows} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent('"stat" does not accept rows data');
  });

  it("reports invalid options", async () => {
    await renderWithApp(
      <Widget config={{ template: "stat", options: {} }} data={shapeFixtures.scalar} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent('Invalid options for "stat"');
  });

  it("reports data that does not match its shape", async () => {
    await renderWithApp(
      <Widget
        config={{ template: "stat", options: { label: "x" } }}
        data={{ shape: "scalar", data: { value: { nested: true } } as never }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("does not match the scalar shape");
  });
});
