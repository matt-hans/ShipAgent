/**
 * Job history panel for the sidebar.
 *
 * Displays shipment job history with search, status filters,
 * delete, and label reprint actions.
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import { cn, formatTimeAgo } from '@/lib/utils';
import { getJobs, deleteJob, getMergedLabelsUrl } from '@/lib/api';
import type { Job, JobSummary } from '@/types/api';
import { SearchIcon, TrashIcon, PrinterIcon } from '@/components/ui/icons';

/** Status badge for job cards. */
export function StatusBadge({ status }: { status: string }) {
  const getStatusStyle = (s: string) => {
    switch (s) {
      case 'completed':
        return 'badge-success';
      case 'running':
        return 'badge-info';
      case 'failed':
        return 'badge-error';
      case 'pending':
        return 'badge-neutral';
      case 'cancelled':
        return 'badge-warning';
      default:
        return 'badge-neutral';
    }
  };

  return (
    <span className={cn('badge text-[10px]', getStatusStyle(status))}>
      {status}
    </span>
  );
}

// Job History Section
export function JobHistorySection({
  onSelectJob,
  activeJobId,
}: {
  onSelectJob: (job: Job | null) => void;
  activeJobId?: string;
}) {
  const { jobListVersion } = useAppState();
  const [jobs, setJobs] = React.useState<JobSummary[]>([]);
  const [search, setSearch] = React.useState('');
  const [filter, setFilter] = React.useState<string>('all');
  const [isLoading, setIsLoading] = React.useState(true);
  const [deletingJobId, setDeletingJobId] = React.useState<string | null>(null);

  // Load job history
  const loadJobs = React.useCallback(async () => {
    try {
      const jobsData = await getJobs({ limit: 20 });
      setJobs(jobsData.jobs);
    } catch (err) {
      console.error('Failed to load history:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Re-fetch when jobListVersion changes (triggered by batch completion)
  React.useEffect(() => {
    loadJobs();
  }, [loadJobs, jobListVersion]);

  // Delete job handler
  const handleDeleteJob = async (e: React.MouseEvent, jobId: string) => {
    e.stopPropagation(); // Prevent selecting the job
    setDeletingJobId(jobId);
    try {
      await deleteJob(jobId);
      // Remove from local state
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
      // Clear selection if deleted job was active
      if (activeJobId === jobId) {
        onSelectJob(null);
      }
    } catch (err) {
      console.error('Failed to delete job:', err);
    } finally {
      setDeletingJobId(null);
    }
  };

  // Filter jobs
  const filteredJobs = React.useMemo(() => {
    return jobs.filter((job) => {
      const matchesSearch = !search || job.original_command?.toLowerCase().includes(search.toLowerCase());
      const matchesFilter = filter === 'all' || job.status === filter;
      return matchesSearch && matchesFilter;
    });
  }, [jobs, search, filter]);

  if (isLoading) {
    return (
      <div className="p-3 space-y-2">
        <div className="h-4 w-24 bg-slate-800 rounded shimmer" />
        <div className="h-12 bg-slate-800 rounded shimmer" />
        <div className="h-12 bg-slate-800 rounded shimmer" />
        <div className="h-12 bg-slate-800 rounded shimmer" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-300">Shipment History</span>
        <span className="text-[10px] font-mono text-slate-500">{jobs.length} jobs</span>
      </div>

      {/* Search */}
      <div className="relative">
        <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search commands..."
          className="w-full pl-8 pr-3 py-2 text-xs font-mono rounded-md bg-void-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
        />
      </div>

      {/* Filter */}
      <div className="flex gap-1">
        {['all', 'completed', 'running', 'failed'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              'px-2 py-1 text-[10px] font-mono rounded transition-colors',
              filter === f
                ? 'bg-slate-700 text-slate-100'
                : 'text-slate-500 hover:text-slate-300'
            )}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Job list */}
      <div className="space-y-1.5 max-h-[300px] overflow-y-auto scrollable">
        {filteredJobs.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-4">No jobs found</p>
        ) : (
          filteredJobs.map((job) => (
            <div
              key={job.id}
              className={cn(
                'group relative w-full text-left p-2.5 rounded-md transition-colors cursor-pointer',
                'border border-transparent',
                activeJobId === job.id
                  ? 'bg-primary/10 border-primary/30'
                  : 'hover:bg-slate-800/50'
              )}
              onClick={() => onSelectJob(job as Job)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  {(() => {
                    if (!job.name?.includes(' → ')) {
                      return (
                        <p className="text-xs text-slate-200 line-clamp-2">
                          {job.name?.startsWith('Command: ') ? job.name.slice(9) : job.original_command || job.name || 'Untitled job'}
                        </p>
                      );
                    }
                    const parts = job.name.split(' → ');
                    const base = parts[0];
                    const refs = parts.slice(1);
                    const maxVisible = 2;
                    const visible = refs.slice(0, maxVisible);
                    const overflow = refs.length - maxVisible;
                    return (
                      <>
                        <p className="text-xs text-slate-200 line-clamp-1">{base}</p>
                        {visible.map((r, i) => (
                          <p key={i} className="text-[10px] text-primary/80 line-clamp-1 mt-0.5">
                            &rarr; {r}
                          </p>
                        ))}
                        {overflow > 0 && (
                          <p className="text-[9px] text-slate-500 italic mt-0.5">
                            +{overflow} more
                          </p>
                        )}
                      </>
                    );
                  })()}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <StatusBadge status={job.status} />
                  {job.status === 'completed' && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        window.open(getMergedLabelsUrl(job.id), '_blank');
                      }}
                      className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity hover:bg-cyan-500/20 text-slate-500 hover:text-cyan-400"
                      title="Reprint labels"
                    >
                      <PrinterIcon className="w-3.5 h-3.5" />
                    </button>
                  )}
                  <button
                    onClick={(e) => handleDeleteJob(e, job.id)}
                    disabled={deletingJobId === job.id}
                    className={cn(
                      'p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity',
                      'hover:bg-error/20 text-slate-500 hover:text-error',
                      deletingJobId === job.id && 'opacity-100 animate-pulse'
                    )}
                    title="Delete job"
                  >
                    <TrashIcon className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-[10px] font-mono text-slate-500">
                  {formatTimeAgo(job.created_at)}
                </span>
                {job.total_rows > 0 && (
                  <>
                    <span className="text-slate-700">·</span>
                    <span className="text-[10px] font-mono text-slate-500">
                      {job.successful_rows}/{job.total_rows} shipments
                    </span>
                  </>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
