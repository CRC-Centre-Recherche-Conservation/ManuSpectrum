/**
 * IIIF Image API request URLs from an image service base URI
 * (`{service}/{region}/{size}/{rotation}/{quality}.{format}`). `max` is the
 * Image API 3 name of the full size; Image API 2.1 servers accept it too.
 */
const base = (service) => String(service).replace(/\/+$/, '');

export const infoJsonUrl = (service) => `${base(service)}/info.json`;

export const imageUrl = (service, { region = 'full', size = 'max' } = {}) =>
    `${base(service)}/${region}/${size}/0/default.jpg`;
