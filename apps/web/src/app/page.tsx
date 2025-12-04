import Link from "next/link";
import Image from "next/image";

export default function HomePage() {
  return (
    <section className="shell">
      <div style={{ marginBottom: 24 }}>
        <Image
          src="/branding/Triphony_solo 1.png"
          alt="Triphony"
          width={600}
          height={300}
          priority
        />
      </div>

      <h1 className="h1">AI Art Studio</h1>

      <p className="p">
        Converts a single prompt into a short cinematic clip. Generated images and videos, a narrated script, and synchronized sound.
      </p>

      <p className="p">
        It opens new worlds for content creators, storytellers, educators, and filmmakers, who can prototype scenes and emotions in seconds.
      </p>

      

      <div className="row" style={{ marginTop: 14 }}>
        <Link className="btn btnPrimary" href="/studio">Open Studio</Link>
        <Link className="btn" href="/library">Browse Library</Link>
      </div>

      <p className="p" style={{ marginTop: 16 }}>
        
      </p>
    </section>
  );
}
