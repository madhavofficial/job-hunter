import { Client } from "/Users/madhavjayam/.npm/_npx/148524a34044d269/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js";
import { StdioClientTransport } from "/Users/madhavjayam/.npm/_npx/148524a34044d269/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js";
import fs from "fs";
import path from "path";

function decodeBody(bodyData) {
  if (!bodyData) return "";
  if (bodyData.includes("<html") || bodyData.includes("<table") || bodyData.includes("<div") || bodyData.includes("http")) {
    return bodyData;
  }
  try {
    return Buffer.from(bodyData, "base64url").toString("utf-8");
  } catch {
    try {
      return Buffer.from(bodyData, "base64").toString("utf-8");
    } catch {
      return bodyData;
    }
  }
}

function cleanText(text) {
  return (text || "")
    .replace(/&amp;/g, "&")
    .replace(/&middot;/g, "·")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

async function main() {
  const transport = new StdioClientTransport({
    command: "node",
    args: ["/Users/madhavjayam/.npm/_npx/148524a34044d269/node_modules/@shinzolabs/gmail-mcp/dist/index.js"],
    env: { ...process.env, PORT: "0" }
  });

  const client = new Client({
    name: "gmail-job-harvester",
    version: "1.0.0"
  }, {
    capabilities: {}
  });

  await client.connect(transport);
  console.log("Connected to Gmail MCP server.");

  // Fetch recent LinkedIn alerts
  const listRes = await client.callTool({
    name: "list_messages",
    arguments: {
      q: "from:jobalerts-noreply@linkedin.com newer_than:7d",
      maxResults: 40
    }
  });

  const parsed = JSON.parse(listRes.content[0].text);
  const messages = parsed.messages || [];
  console.log(`Found ${messages.length} LinkedIn alert emails in the last 7 days.`);

  const discoveredJobs = [];
  const seenJobIds = new Set();

  for (let i = 0; i < messages.length; i++) {
    const msgMeta = messages[i];
    process.stdout.write(`Processing email [${i + 1}/${messages.length}] (${msgMeta.id})... `);
    try {
      const msgRes = await client.callTool({
        name: "get_message",
        arguments: {
          id: msgMeta.id,
          includeBodyHtml: true
        }
      });

      const msg = JSON.parse(msgRes.content[0].text);
      const parts = msg.payload?.parts || [];
      
      let html = "";
      let plainText = "";
      for (const part of parts) {
        if (part.mimeType === "text/html" && part.body?.data) {
          html = decodeBody(part.body.data);
        } else if (part.mimeType === "text/plain" && part.body?.data) {
          plainText = decodeBody(part.body.data);
        }
      }

      if (!html && msg.payload?.body?.data) {
        html = decodeBody(msg.payload.body.data);
      }

      let emailJobsCount = 0;

      // Method 1: HTML job card matching
      if (html) {
        const jobCardRegex = /<a[^>]+href="(?<url>https:\/\/www\.linkedin\.com\/comm\/jobs\/view\/(?<job_id>\d+)[^"]*)"[^>]*class="[^"]*(?:font-bold|text-system-blue-50)[^"]*"[^>]*>\s*(?<title>[^<]+)\s*<\/a>[\s\S]*?<p[^>]*class="[^"]*text-system-gray-100[^"]*"[^>]*>\s*(?<meta>[^<]+)\s*<\/p>/gi;

        let match;
        while ((match = jobCardRegex.exec(html)) !== null) {
          const rawJobId = match.groups.job_id;
          const jobId = `li-${rawJobId}`;
          if (seenJobIds.has(jobId)) continue;
          seenJobIds.add(jobId);

          const title = cleanText(match.groups.title);
          const rawMeta = cleanText(match.groups.meta);
          const metaParts = rawMeta.split("·").map(s => s.trim());
          const company = metaParts[0] || "Unknown";
          const location = metaParts[1] || "India";

          discoveredJobs.push({
            job_id: jobId,
            title: title,
            company: company,
            location: location,
            job_url: `https://www.linkedin.com/jobs/view/${rawJobId}`,
            job_url_direct: `https://www.linkedin.com/jobs/view/${rawJobId}`,
            site: "linkedin",
            date_posted: new Date().toISOString().split("T")[0]
          });
          emailJobsCount++;
        }
      }

      // Method 2: Plain text fallback if HTML parsing yielded 0
      if (emailJobsCount === 0 && plainText) {
        const textRegex = /(?<title>[^\r\n]+)[\r\n]+(?<company>[^\r\n]+)[\r\n]+(?<location>[^\r\n]+)[\r\n]+(?:[^\r\n]*alumn[^\r\n]*[\r\n]+)?(?:Apply with [^\r\n]*[\r\n]+)?View job:\s*https:\/\/www\.linkedin\.com\/comm\/jobs\/view\/(?<job_id>\d+)/gi;
        let match;
        while ((match = textRegex.exec(plainText)) !== null) {
          const rawJobId = match.groups.job_id;
          const jobId = `li-${rawJobId}`;
          if (seenJobIds.has(jobId)) continue;
          seenJobIds.add(jobId);

          const title = cleanText(match.groups.title);
          const company = cleanText(match.groups.company);
          const location = cleanText(match.groups.location);

          discoveredJobs.push({
            job_id: jobId,
            title: title,
            company: company,
            location: location,
            job_url: `https://www.linkedin.com/jobs/view/${rawJobId}`,
            job_url_direct: `https://www.linkedin.com/jobs/view/${rawJobId}`,
            site: "linkedin",
            date_posted: new Date().toISOString().split("T")[0]
          });
          emailJobsCount++;
        }
      }

      console.log(`Extracted ${emailJobsCount} jobs.`);
    } catch (err) {
      console.log(`Failed: ${err.message}`);
    }
  }

  await client.close();
  console.log(`\n======================================================`);
  console.log(`✓ Total unique jobs harvested from LinkedIn alerts: ${discoveredJobs.length}`);
  console.log(`======================================================`);

  const outPath = path.resolve("./data/harvested_email_jobs.json");
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(discoveredJobs, null, 2), "utf-8");
  console.log(`Saved harvested jobs to ${outPath}`);
}

main().catch(console.error);
