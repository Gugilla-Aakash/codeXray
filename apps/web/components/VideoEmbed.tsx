"use client";

/* Click-to-play YouTube facade: thumbnail + play button until clicked,
   then swaps in the privacy-enhanced iframe. Zero tracking before play. */

import { useState } from "react";

export default function VideoEmbed({
  id,
  title,
  channel,
  duration,
}: {
  id: string;
  title: string;
  channel: string;
  duration: string;
}) {
  const [playing, setPlaying] = useState(false);

  if (playing) {
    return (
      <div className="video">
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`}
          title={title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          loading="lazy"
        />
      </div>
    );
  }

  return (
    <figure className="video-wrap">
      <button
        type="button"
        className="video"
        onClick={() => setPlaying(true)}
        aria-label={`Play video: ${title}`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`https://i.ytimg.com/vi/${id}/hqdefault.jpg`}
          alt=""
          loading="lazy"
        />
        <span className="video__play" aria-hidden="true">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5v14l11-7z" />
          </svg>
        </span>
        <span className="video__dur" aria-hidden="true">
          {duration}
        </span>
      </button>
      <figcaption>
        <strong>{title}</strong>
        <span>{channel}</span>
      </figcaption>
    </figure>
  );
}
