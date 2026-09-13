package com.claimguard.domain;

/**
 * The kinds of real-world thing a claim can reference and that a fraud
 * ring can therefore be stitched together through: a phone number, an
 * address, or a repair shop.
 */
public enum EntityType {
    PHONE,
    ADDRESS,
    SHOP
}
