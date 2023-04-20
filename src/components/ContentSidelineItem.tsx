// Import required libraries and components
import React from 'react';

// Define TypeScript interfaces for the content data and component props
interface Content {
  id: number;
  title: string;
  summary: string;
  labels: string[];
}

interface ContentSidelineItem {
  content: Content;
}

// Create the ContentSidelineItem component
const ContentSidelineItem: React.FC<ContentSidelineItem> = ({content}) => {
  return (
    <div className="box content-sideline-item">
      <div className="content">
        <h3 className="title is-4">{content.title}</h3>
        <p>{content.summary.substring(0, 100) + '...'}</p>
        <div className="tags">
          {content.labels.map((label, index) => (
            <span key={index} className="tag">
              {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ContentSidelineItem;
