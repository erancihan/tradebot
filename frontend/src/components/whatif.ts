// The What-if page: post a plan, poll the job, show the result card.
//
// Phone first: one column, one primary button. The job runs on the server
// (`POST /api/whatif`) and is polled through the shared `/api/jobs/{id}`.

import { getJob, submitWhatIf } from "../api/client";
import type { JobView, Provenance, WhatIfRequest } from "../types";

const POLL_MS = 500;

export function whatIf() {
  return {
    state: "idle",
    error: "",
    summary: null as Record<string, number | string> | null,
    provenance: null as Provenance | null,

    buildRequest(): WhatIfRequest {
      return {
        symbols: ["DEMO"],
        source: "synthetic",
        initial_cash: 10000,
        monthly_contribution: 200,
      };
    },

    async submit() {
      this.state = "running";
      this.error = "";
      this.summary = null;
      this.provenance = null;
      try {
        const { job_id } = await submitWhatIf(this.buildRequest());
        await this.poll(job_id);
      } catch (err) {
        this.state = "error";
        this.error = String(err);
      }
    },

    async poll(jobId: string) {
      const job: JobView = await getJob(jobId);
      if (job.state === "done") {
        this.state = "done";
        this.summary = job.summary ?? {};
        this.provenance = job.provenance ?? null;
      } else if (job.state === "error") {
        this.state = "error";
        this.error = job.error ?? "job failed";
      } else {
        setTimeout(() => {
          void this.poll(jobId);
        }, POLL_MS);
      }
    },
  };
}
