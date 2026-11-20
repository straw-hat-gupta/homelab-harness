import Markdown from "react-markdown";
import { z } from "zod";

import { defineTemplate } from "@/registry/define";

export const template = defineTemplate({
  name: "markdown",
  summary: "A Markdown document, such as a lab document section",
  accepts: ["markdown"],
  options: z.object({}),
  // react-markdown renders no raw HTML and drops unsafe URLs (javascript: and
  // the like) by default; lab documents carry target text, so keep it that way.
  render: ({ data }) => (
    <div className="markdown space-y-3 text-sm leading-relaxed">
      <Markdown>{data.markdown}</Markdown>
    </div>
  ),
});
