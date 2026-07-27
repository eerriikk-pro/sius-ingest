import Link from "next/link";

import { SignOutButton } from "@/components/sign-out-button";

interface AccountNavProps {
  email: string;
  isAdmin: boolean;
}

export function AccountNav({ email, isAdmin }: AccountNavProps) {
  return (
    <nav className="account-nav" aria-label="Account">
      <span title={email}>{email}</span>
      <Link href="/">Shots</Link>
      <Link href="/account">Access</Link>
      {isAdmin ? <Link href="/admin/access">Admin</Link> : null}
      <SignOutButton />
    </nav>
  );
}
